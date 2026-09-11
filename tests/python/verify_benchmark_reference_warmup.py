"""Run the mock benchmark and verify the direct-reference warmup contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import wave
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        work_dir = Path(directory)
        result_path = work_dir / "result.json"
        reference_path = work_dir / "reference.wav"
        with wave.open(str(reference_path), "wb") as reference:
            reference.setnchannels(1)
            reference.setsampwidth(2)
            reference.setframerate(24_000)
            reference.writeframes(b"\x00\x00" * 24)

        command = [
            str(args.benchmark),
            "--mock",
            "--warmup-text",
            "Warmup request",
            "--warmup-reference-audio-path",
            str(reference_path),
            "--warmup-reference-text",
            "Reference",
            "--warmups",
            "1",
            "--requests",
            "1",
            "--result-json",
            str(result_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
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
        if not warmup.get("has_reference_audio"):
            raise AssertionError(f"warmup did not receive reference audio: {warmup!r}")
        if warmup.get("voice_id") != "":
            raise AssertionError(
                f"reference warmup unexpectedly had voice_id: {warmup!r}"
            )

        voice_result_path = work_dir / "voice-result.json"
        voice_command = [
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
            str(voice_result_path),
        ]
        voice_run = subprocess.run(
            voice_command, capture_output=True, text=True, check=False
        )
        if voice_run.returncode != 0:
            raise AssertionError(voice_run.stderr)
        voice_metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in voice_run.stderr.splitlines()
            if line.startswith("qtb_metric ")
        ]
        voice_warmup = next(
            metric
            for metric in voice_metrics
            if metric.get("event") == "request_received"
            and metric.get("request_id") == 1
        )
        if voice_warmup.get("voice_id") != "test-profile":
            raise AssertionError(
                f"registered-voice warmup lost voice_id: {voice_warmup!r}"
            )
        if voice_warmup.get("has_reference_audio"):
            raise AssertionError(
                f"registered-voice warmup unexpectedly had reference audio: "
                f"{voice_warmup!r}"
            )

        conflict = subprocess.run(
            [*command, "--voice-id", "test-profile"],
            capture_output=True,
            text=True,
            check=False,
        )
        if conflict.returncode == 0:
            raise AssertionError("voice_id and direct-reference warmup must conflict")
        expected_error = (
            "--voice-id cannot be combined with --warmup-reference-audio-path"
        )
        if expected_error not in conflict.stderr:
            raise AssertionError(conflict.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
