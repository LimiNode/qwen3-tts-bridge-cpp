"""Regression checks for marker-aligned CMP50HX ETW analysis helpers."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MODULE = _ROOT / "scripts" / "Cmp50hxEtwMarkerAnalysis.psm1"
_POWERSHELL = "powershell.exe"
_REQUEST_START = "qwen_tts_bridge.playback.request_start"
_QUEUE_EMPTY_PREFIX = "qwen_tts_bridge.playback.queue_empty_before_later_chunk"


def _invoke(command: str) -> object:
    completed = subprocess.run(
        [
            _POWERSHELL,
            "-NoProfile",
            "-Command",
            f"Import-Module '{_MODULE}'; {command}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class Cmp50hxEtwMarkerAnalysisTest(unittest.TestCase):
    def test_parses_and_validates_expected_marker_sequence(self) -> None:
        queue_marker_1 = f"{_QUEUE_EMPTY_PREFIX} index=1"
        queue_marker_2 = f"{_QUEUE_EMPTY_PREFIX} index=2"
        result = _invoke(
            "$lines = @("
            f"' Mark, 100, {_REQUEST_START}', "
            f"' Mark, 200, {queue_marker_1}', "
            f"' Mark, 300, {queue_marker_2}'); "
            "$markers = @(Get-Cmp50hxPlaybackMarkers -DumperLines $lines); "
            "Assert-Cmp50hxPlaybackMarkerSequence "
            "-Markers $markers -ExpectedMarkerCount 3 | "
            "ConvertTo-Json -Depth 5 -Compress"
        )
        self.assertEqual(result["request_start_timestamp_us"], 100)
        self.assertEqual(result["queue_empty_marker_count"], 2)
        self.assertEqual(
            [marker["queue_index"] for marker in result["markers"][1:]], [1, 2]
        )

    def test_marker_validation_rejects_duplicate_queue_index(self) -> None:
        queue_marker_1 = f"{_QUEUE_EMPTY_PREFIX} index=1"
        command = (
            f"Import-Module '{_MODULE}'; "
            f"$lines = @('Mark, 100, {_REQUEST_START}', "
            f"'Mark, 200, {queue_marker_1}', "
            f"'Mark, 300, {queue_marker_1}'); "
            "$markers = @(Get-Cmp50hxPlaybackMarkers -DumperLines $lines); "
            "Assert-Cmp50hxPlaybackMarkerSequence "
            "-Markers $markers -ExpectedMarkerCount 3"
        )
        completed = subprocess.run(
            [_POWERSHELL, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("index=1", completed.stderr)

    def test_aggregates_worker_and_competing_dxgkrnl_events_by_marker_window(
        self,
    ) -> None:
        result = _invoke(
            "$window = [pscustomobject]@{window_id='queue_empty_1'; "
            "marker_text='marker'; marker_timestamp_us=200; "
            "start_timestamp_us=100; end_timestamp_us=250}; "
            "$windows = @($window); "
            "$lines = @("
            "'Microsoft-Windows-DxgKrnl/DmaPacket/win:Info, 150, "
            "python.exe (42), 1', "
            "'Microsoft-Windows-DxgKrnl/QueuePacket/win:Info, 220, "
            "chrome.exe (77), 1', "
            "'Microsoft-Windows-DxgKrnl/QueuePacket/win:Info, 260, "
            "python.exe (42), 1'); "
            "Get-Cmp50hxMarkerWindowDxgKrnlSummary -DumperLines $lines "
            "-Windows $windows -WorkerPid 42 | "
            "ConvertTo-Json -Depth 5 -Compress"
        )
        self.assertEqual(result["worker_dxgkrnl_event_count"], 1)
        self.assertEqual(result["worker_dxgkrnl_event_types"], {"DmaPacket": 1})
        self.assertEqual(
            result["top_competing_processes"],
            [{"process": "chrome.exe (77)", "dxgkrnl_event_count": 1}],
        )


if __name__ == "__main__":
    unittest.main()
