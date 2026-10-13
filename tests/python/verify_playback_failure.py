"""Verify that a playback sink failure is not reported as successful synthesis."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True, type=Path)
    return parser.parse_args()


def run_failure_case(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "playback failed" in output, output
    assert "completed request" not in output, output


def main() -> int:
    args = parse_args()
    command = [
        str(args.player),
        "--mock",
        "--mock-playback-sink",
        "--mock-playback-fail-after",
        "1",
        "--mock-chunks",
        "3",
        "--mock-chunk-ms",
        "20",
        "--no-tail",
        "--text",
        "Playback failure smoke.",
    ]
    run_failure_case(command)

    prepare_command = [
        str(args.player),
        "--mock",
        "--mock-playback-sink",
        "--mock-playback-fail-after",
        "0",
        "--mock-playback-fail-stage",
        "prepare",
        "--mock-chunks",
        "2",
        "--mock-chunk-ms",
        "20",
        "--no-tail",
        "--text",
        "Playback prepare failure smoke.",
    ]
    run_failure_case(prepare_command)

    terminal_tail_command = [
        str(args.player),
        "--mock",
        "--mock-playback-sink",
        "--mock-playback-fail-after",
        "3",
        "--mock-chunks",
        "3",
        "--mock-chunk-ms",
        "20",
        "--text",
        "Playback terminal-tail failure.",
    ]
    run_failure_case(terminal_tail_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
