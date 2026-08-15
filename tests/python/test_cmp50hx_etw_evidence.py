"""Regression checks for the ETW evidence classification contract."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MODULE = _ROOT / "scripts" / "Cmp50hxEtwEvidence.psm1"
_POWERSHELL = "powershell.exe"


def _classify(trace_stats: str) -> dict[str, object]:
    command = (
        f"Import-Module '{_MODULE}'; "
        f"$result = Get-Cmp50hxEventLossStatus -TraceStatsText '{trace_stats}'; "
        "$result | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _classify_semantics(trace_stats: str) -> dict[str, object]:
    command = (
        f"Import-Module '{_MODULE}'; "
        f"$result = Get-Cmp50hxTraceSemanticStatus -TraceStatsText '{trace_stats}'; "
        "$result | ConvertTo-Json -Depth 4 -Compress"
    )
    completed = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class Cmp50hxEtwEvidenceTest(unittest.TestCase):
    def test_event_loss_status_fails_closed(self) -> None:
        cases = [
            ("Total # Lost Buffers : 0\nTotal # Lost Events : 0", "verified_zero", 0),
            ("Total # Lost Buffers : 0\nTotal # Lost Events : 17", "nonzero", 17),
            (
                "Total # Lost Buffers : 0\nTotal # Lost Events : 0\n"
                "# Lost Buffers : 0\n# Lost Events : 4",
                "nonzero",
                4,
            ),
            ("Trace was successfully saved.", "unparseable", None),
        ]
        for trace_stats, expected_status, expected_events in cases:
            with self.subTest(trace_stats=trace_stats):
                result = _classify(trace_stats)
                self.assertEqual(result["event_loss_status"], expected_status)
                self.assertEqual(result["lost_event_count"], expected_events)

    def test_outlier_requires_completion_and_threshold(self) -> None:
        cases = [(True, 1, True), (True, 0, False), (False, 3, False)]
        for completed, queue_empty, expected in cases:
            with self.subTest(completed=completed, queue_empty=queue_empty):
                command = (
                    f"Import-Module '{_MODULE}'; "
                    "Test-Cmp50hxPlaybackOutlier "
                    f"-PlaybackCompleted ${str(completed).lower()} "
                    f"-QueueEmptyBeforeLaterChunkCount {queue_empty} "
                    "-QueueEmptyThreshold 1"
                )
                result = subprocess.run(
                    [_POWERSHELL, "-NoProfile", "-Command", command],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.stdout.strip().lower(), str(expected).lower())

    def test_semantic_trace_requires_scheduler_records(self) -> None:
        trace_stats = "\n".join(
            (
                "{802ec45a-1e99-4b83-9920-87c98277ba9d}  12  34 "
                "Microsoft-Windows-DxgKrnl",
                "0x00af 0x0008 0x01 0x01 0x11 0x00 0x1 4 12 "
                "Microsoft-Windows-DxgKrnl/DmaPacket/win:Start",
                "0x00b2 0x0009 0x01 0x01 0x11 0x00 0x1 8 24 "
                "Microsoft-Windows-DxgKrnl/QueuePacket/win:Start",
                "Thread: CSwitch",
            )
        )
        result = _classify_semantics(trace_stats)
        self.assertTrue(result["dxgkrnl_present"])
        self.assertTrue(result["cswitch_present"])
        self.assertTrue(result["scheduler_event_presence_verified"])
        self.assertTrue(result["semantic_trace_valid"])
        self.assertEqual(result["scheduler_event_count"], 12)

    def test_semantic_trace_fails_closed_without_scheduler_records(self) -> None:
        trace_stats = """
{802ec45a-1e99-4b83-9920-87c98277ba9d}  12  34  Microsoft-Windows-DxgKrnl
Thread: CSwitch
""".strip()
        result = _classify_semantics(trace_stats)
        self.assertFalse(result["semantic_trace_valid"])
