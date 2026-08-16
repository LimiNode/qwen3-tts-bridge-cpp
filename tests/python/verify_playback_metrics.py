"""Exercise the opt-in WaveOut queue-starvation metrics with the mock worker."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unbuffered_output = args.output
    buffered_output = args.output.with_name(f"{args.output.stem}-prebuffered.json")
    for output in (unbuffered_output, buffered_output):
        if output.exists():
            output.unlink()

    unbuffered_command = [
        str(args.player),
        "--mock",
        "--text",
        "Playback metrics smoke.",
        "--mock-chunks",
        "3",
        "--mock-chunk-ms",
        "40",
        "--mock-chunk-delay",
        "0.15",
        "--playback-metrics-file",
        str(unbuffered_output),
    ]
    subprocess.run(unbuffered_command, check=True, timeout=30)

    result = json.loads(unbuffered_output.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert result["measurement"] == "waveout_queue_starvation_proxy"
    assert result["playback_prebuffer_ms"] == 0
    assert result["etw_playback_markers_enabled"] is False
    assert result["etw_playback_marker_count"] == 0
    assert result["playback_completed"] is True
    if result["audio_chunk_count"] == 0:
        print("WaveOut device unavailable; playback queue assertions skipped.")
    else:
        assert result["audio_chunk_count"] == 3
        assert len(result["chunks"]) == 3
        assert result["playback_started_ms"] is not None
        assert result["queue_empty_before_later_chunk_count"] >= 1
        assert result["chunks"][0]["inter_arrival_ms"] is None
        assert any(
            chunk["queue_empty_before_later_chunk"] for chunk in result["chunks"][1:]
        )

    buffered_command = [
        str(args.player),
        "--mock",
        "--text",
        "Playback prebuffer smoke.",
        "--mock-chunks",
        "3",
        "--mock-chunk-ms",
        "250",
        "--mock-chunk-delay",
        "0.15",
        "--playback-prebuffer-ms",
        "400",
        "--playback-metrics-file",
        str(buffered_output),
    ]
    subprocess.run(buffered_command, check=True, timeout=30)

    buffered_result = json.loads(buffered_output.read_text(encoding="utf-8"))
    assert buffered_result["schema_version"] == 1
    assert buffered_result["measurement"] == "waveout_queue_starvation_proxy"
    assert buffered_result["playback_prebuffer_ms"] == 400
    assert buffered_result["playback_completed"] is True
    if buffered_result["audio_chunk_count"] == 0:
        print("WaveOut device unavailable; playback prebuffer assertions skipped.")
    else:
        assert buffered_result["audio_chunk_count"] == 3
        assert len(buffered_result["chunks"]) == 3
        assert buffered_result["playback_started_ms"] is not None
        assert (
            buffered_result["chunks"][0]["arrival_ms"]
            <= buffered_result["playback_started_ms"]
            <= buffered_result["chunks"][1]["arrival_ms"]
        )
        assert buffered_result["queue_empty_before_later_chunk_count"] == 0
        assert all(
            not chunk["queue_empty_before_later_chunk"]
            for chunk in buffered_result["chunks"]
        )

    missing_metrics = subprocess.run(
        [str(args.player), "--mock", "--etw-playback-markers"],
        capture_output=True,
        text=True,
    )
    assert missing_metrics.returncode != 0
    assert "requires --playback-metrics-file" in missing_metrics.stderr
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
