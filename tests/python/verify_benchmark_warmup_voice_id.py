"""Run the mock benchmark and verify that warmup receives the selected voice."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        result_path = Path(directory) / "result.json"
        completed = subprocess.run(
            [
                str(args.benchmark),
                "--mock",
                "--warmup-text",
                "Warmup request",
                "--voice-id",
                "test-profile",
                "--warmups",
                "1",
                "--requests",
                "1",
                "--result-json",
                str(result_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in completed.stderr.splitlines()
            if line.startswith("qtb_metric ")
        ]
        warmup = next(
            metric
            for metric in metrics
            if metric.get("event") == "request_received"
            and metric.get("request_id") == 1
        )
        if warmup.get("voice_id") != "test-profile":
            raise AssertionError(f"warmup voice_id was not forwarded: {warmup!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
