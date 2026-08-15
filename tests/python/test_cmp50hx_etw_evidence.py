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
                    f"-QueueEmptyBeforeLaterChunkCount {queue_empty} -QueueEmptyThreshold 1"
                )
                result = subprocess.run(
                    [_POWERSHELL, "-NoProfile", "-Command", command],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.stdout.strip().lower(), str(expected).lower())
