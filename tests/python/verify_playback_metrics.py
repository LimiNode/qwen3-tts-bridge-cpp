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

    subprocess.run(
        [
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
            str(args.output),
        ],
        check=True,
    )

    result = json.loads(args.output.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert result["measurement"] == "waveout_queue_starvation_proxy"
    assert result["playback_completed"] is True
    if result["audio_chunk_count"] == 0:
        print("WaveOut device unavailable; playback queue assertions skipped.")
        return 0
    assert result["audio_chunk_count"] == 3
    assert len(result["chunks"]) == 3
    assert result["queue_empty_before_later_chunk_count"] >= 1
    assert result["chunks"][0]["inter_arrival_ms"] is None
    assert any(
        chunk["queue_empty_before_later_chunk"]
        for chunk in result["chunks"][1:]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
