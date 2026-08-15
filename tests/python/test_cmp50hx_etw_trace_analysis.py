"""Regression checks for offline CMP50HX ETW attribution parsing."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MODULE = _ROOT / "scripts" / "Cmp50hxEtwTraceAnalysis.psm1"
_POWERSHELL = "powershell.exe"


def _invoke(function: str, argument: str) -> dict[str, object]:
    command = (
        f"Import-Module '{_MODULE}'; "
        f"$result = {function} {argument}; "
        "$result | ConvertTo-Json -Depth 4 -Compress"
    )
    completed = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class Cmp50hxEtwTraceAnalysisTest(unittest.TestCase):
    def test_resolves_worker_from_player_parent_pid(self) -> None:
        process_report = (
            "100, 200, Process, ptr, qwen_tts_play.exe ( 9576), 1, 1, key\n"
            "100, 200, Process, ptr, python.exe (98836), 9576, 1, key\n"
            "100, 200, Process, ptr, python.exe (100), 2, 1, key"
        )
        result = _invoke(
            "Get-Cmp50hxWorkerProcess",
            f"-ProcessReport '{process_report}'",
        )
        self.assertEqual(result["worker_process_status"], "resolved")
        self.assertEqual(result["player_pids"], [9576])
        self.assertEqual(result["worker_pids"], [98836])

    def test_requires_exactly_one_worker(self) -> None:
        process_report = "100, 200, Process, ptr, qwen_tts_play.exe ( 9576), 1, 1, key"
        result = _invoke(
            "Get-Cmp50hxWorkerProcess",
            f"-ProcessReport '{process_report}'",
        )
        self.assertEqual(result["worker_process_status"], "unresolved")

    def test_counts_worker_dxgkrnl_events_only(self) -> None:
        lines = (
            "Microsoft-Windows-DxgKrnl/DmaPacket/win:Info, 1, python.exe (98836)\n"
            "Microsoft-Windows-DxgKrnl/QueuePacket/win:Stop, 2, python.exe (98836)\n"
            "Microsoft-Windows-DxgKrnl/DmaPacket/win:Info, 3, python.exe (77)"
        )
        result = _invoke(
            "Get-Cmp50hxDxgKrnlEventSummary",
            "-DumperLines @("
            f"'{lines.splitlines()[0]}', "
            f"'{lines.splitlines()[1]}', "
            f"'{lines.splitlines()[2]}') "
            "-WorkerPid 98836",
        )
        self.assertEqual(result["worker_dxgkrnl_event_count"], 2)
        self.assertEqual(
            result["worker_dxgkrnl_event_types"],
            {"DmaPacket": 1, "QueuePacket": 1},
        )

    def test_requires_cswitch_and_dxgkrnl_events_for_attribution(self) -> None:
        cases = [
            (True, 1, True, []),
            (False, 1, False, ["worker_cswitch_absent"]),
            (True, 0, False, ["worker_dxgkrnl_events_absent"]),
        ]
        for cswitch_present, event_count, expected_valid, expected_reasons in cases:
            with self.subTest(cswitch_present=cswitch_present, event_count=event_count):
                result = _invoke(
                    "Get-Cmp50hxWorkerAttributionStatus",
                    "-WorkerCswitchPresent "
                    f"${str(cswitch_present).lower()} "
                    f"-WorkerDxgKrnlEventCount {event_count}",
                )
                self.assertEqual(result["worker_attribution_valid"], expected_valid)
                self.assertEqual(result["invalid_reasons"], expected_reasons)
