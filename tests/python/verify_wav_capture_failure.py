"""Verify optional WAV capture failure does not cancel synthesis or playback."""

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


def remove_artifacts(path: Path) -> None:
    path.unlink(missing_ok=True)
    for temporary in path.parent.glob(f"{path.name}.tmp.*"):
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    remove_artifacts(args.output)
    metrics = args.output.with_name(f"{args.output.stem}.metrics.json")
    metrics.unlink(missing_ok=True)

    result = subprocess.run(
        [
            str(args.player),
            "--mock",
            "--mock-playback-sink",
            "--mock-wav-capture-failure",
            "--mock-chunks",
            "3",
            "--mock-chunk-ms",
            "20",
            "--no-tail",
            "--text",
            "Optional WAV capture failure smoke.",
            "--wav-capture-file",
            str(args.output),
            "--playback-metrics-file",
            str(metrics),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "WAV capture writer failed" in output, output
    assert "playback failed" not in output, output
    assert "request cancelled" not in output, output
    assert not args.output.exists(), "failed optional capture was published"
    assert not list(args.output.parent.glob(f"{args.output.name}.tmp.*"))

    playback = json.loads(metrics.read_text(encoding="utf-8"))
    assert playback["playback_completed"] is True
    assert playback["audio_chunk_count"] == 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
