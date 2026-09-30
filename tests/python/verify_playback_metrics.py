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
    if args.output.exists():
        args.output.unlink()
    prebuffer_output = args.output.with_stem(f"{args.output.stem}-prebuffer")
    if prebuffer_output.exists():
        prebuffer_output.unlink()
    tail_output = args.output.with_stem(f"{args.output.stem}-tail")
    if tail_output.exists():
        tail_output.unlink()
    oversize_output = args.output.with_stem(f"{args.output.stem}-oversize")
    if oversize_output.exists():
        oversize_output.unlink()

    command = [
        str(args.player),
        "--mock",
        "--mock-playback-sink",
        "--text",
        "Playback metrics smoke.",
        "--mock-chunks",
        "4",
        "--mock-chunk-ms",
        "150",
        "--mock-chunk-delay",
        "0.2",
        "--playback-metrics-file",
        str(args.output),
    ]
    subprocess.run(command, check=True, timeout=30)

    result = json.loads(args.output.read_text(encoding="utf-8"))
    assert result["schema_version"] == 2
    assert result["measurement"] == "waveout_queue_starvation_proxy"
    assert (
        result["first_waveout_submission_ms"] is None
        or result["first_waveout_submission_ms"] >= 0
    )
    assert result["etw_playback_markers_enabled"] is False
    assert result["etw_playback_marker_count"] == 0
    assert result["playback_completed"] is True
    assert result["audio_chunk_count"] == 4
    assert len(result["chunks"]) == 4
    assert result["first_waveout_submission_ms"] is not None
    assert result["queue_empty_before_later_chunk_count"] >= 1
    assert result["chunks"][0]["inter_arrival_ms"] is None
    assert any(
        chunk["queue_empty_before_later_chunk"] for chunk in result["chunks"][1:]
    )
    assert all(
        chunk["admission_ms"] >= chunk["arrival_ms"]
        for chunk in result["chunks"]
    )
    assert all(chunk["backpressure_wait_ms"] >= 0 for chunk in result["chunks"])

    prebuffer_command = [
        *command,
        "--playback-prebuffer-chunks",
        "2",
    ]
    output_index = prebuffer_command.index(str(args.output))
    prebuffer_command[output_index] = str(prebuffer_output)
    subprocess.run(prebuffer_command, check=True, timeout=30)

    prebuffer_result = json.loads(prebuffer_output.read_text(encoding="utf-8"))
    assert prebuffer_result["audio_chunk_count"] == 4
    assert prebuffer_result["queue_empty_before_later_chunk_count"] == 0
    assert prebuffer_result["first_waveout_submission_ms"] is not None
    assert (
        prebuffer_result["first_waveout_submission_ms"]
        > prebuffer_result["chunks"][0]["arrival_ms"]
    )

    tail_command = [*command, "--tail"]
    output_index = tail_command.index(str(args.output))
    tail_command[output_index] = str(tail_output)
    subprocess.run(tail_command, check=True, timeout=30)

    tail_result = json.loads(tail_output.read_text(encoding="utf-8"))
    assert tail_result["audio_chunk_count"] == 5
    assert tail_result["total_audio_duration_ms"] == 685.0
    assert tail_result["chunks"][0]["audio_duration_ms"] == 135.0
    assert tail_result["chunks"][-1]["audio_duration_ms"] == 100.0

    # A chunk larger than the 250 ms backpressure threshold must not force the
    # sink to wait until that whole chunk completes. Backpressure is based on
    # remaining playout-ahead audio, so the next chunk is admitted while the
    # current one still has audio left.
    oversize_command = [
        str(args.player),
        "--mock",
        "--mock-playback-sink",
        "--text",
        "Oversized playback chunk smoke.",
        "--mock-chunks",
        "3",
        "--mock-chunk-ms",
        "640",
        "--mock-chunk-delay",
        "0.05",
        "--playback-metrics-file",
        str(oversize_output),
    ]
    subprocess.run(oversize_command, check=True, timeout=30)
    oversize_result = json.loads(oversize_output.read_text(encoding="utf-8"))
    assert oversize_result["schema_version"] == 2
    assert oversize_result["audio_chunk_count"] == 3
    assert oversize_result["queue_empty_before_later_chunk_count"] == 0
    assert oversize_result["chunks"][1]["backpressure_wait_ms"] > 100.0

    missing_metrics = subprocess.run(
        [str(args.player), "--mock", "--etw-playback-markers"],
        capture_output=True,
        text=True,
    )
    assert missing_metrics.returncode != 0
    assert "requires --playback-metrics-file" in missing_metrics.stderr

    invalid_prebuffer = subprocess.run(
        [str(args.player), "--mock", "--playback-prebuffer-chunks", "0"],
        capture_output=True,
        text=True,
    )
    assert invalid_prebuffer.returncode != 0
    assert "must be greater than zero" in invalid_prebuffer.stderr
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
