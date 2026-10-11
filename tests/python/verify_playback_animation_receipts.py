from __future__ import annotations

import argparse
import json
import pathlib
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = pathlib.Path(args.output)
    output.unlink(missing_ok=True)
    completed = subprocess.run(
        [
            args.player,
            "--mock",
            "--mock-playback-sink",
            "--text",
            "Playback animation smoke",
            "--mock-chunks",
            "3",
            "--mock-chunk-ms",
            "20",
            "--tail-fade-ms",
            "5",
            "--tail-silence-ms",
            "5",
            "--playback-animation-fps",
            "60",
            "--playback-animation-receipts-file",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"player failed ({completed.returncode}):\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
    ]
    selections = [record for record in records if record.get("type") != "diagnostic"]
    if not selections:
        raise AssertionError("playback animation receipt file is empty")
    selected = [record for record in selections if record.get("status") == "selected"]
    if not selected:
        raise AssertionError(f"no selected cue in receipts: {selections}")
    if not any(record.get("mouth_open", 0.0) > 0.0 for record in selected):
        raise AssertionError("selected receipts never exposed a non-zero mouth_open")
    if any(record.get("playback_epoch", 0) == 0 for record in selections):
        raise AssertionError("receipt has no playback epoch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
