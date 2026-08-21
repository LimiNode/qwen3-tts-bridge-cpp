"""Exercise diagnostic raw PCM capture with the deterministic mock worker."""

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


def remove_capture(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_name(f"{path.name}.json").unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    remove_capture(args.output)
    command = [
        str(args.player),
        "--mock",
        "--text",
        "PCM capture smoke.",
        "--mock-chunks",
        "4",
        "--mock-chunk-ms",
        "150",
        "--pcm-capture-file",
        str(args.output),
    ]
    subprocess.run(command, check=True, timeout=30)

    metadata_path = args.output.with_name(f"{args.output.name}.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_bytes = 4 * 24_000 * 150 // 1_000 * 2
    assert args.output.stat().st_size == expected_bytes
    assert metadata == {
        "schema_version": 1,
        "measurement": "raw_s16le_pcm_capture",
        "completed": True,
        "audio_chunk_count": 4,
        "byte_count": expected_bytes,
        "audio_format": {
            "sample_format": "s16le",
            "sample_rate": 24_000,
            "channels": 1,
        },
    }

    duplicate = subprocess.run(command, capture_output=True, text=True)
    assert duplicate.returncode != 0
    assert "refusing to overwrite existing PCM capture file" in duplicate.stderr

    interactive = subprocess.run(
        [str(args.player), "--mock", "--pcm-capture-file", str(args.output)],
        capture_output=True,
        text=True,
    )
    assert interactive.returncode != 0
    assert "requires one-shot --text playback" in interactive.stderr
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
