"""Exercise the fail-closed output contract of qwen_tts_save_wav."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def expect_failure(
    command: list[str], output: Path, *, preserve_existing: bool = False
) -> None:
    completed = run(command)
    if completed.returncode == 0:
        raise AssertionError(
            f"expected failure, got success:\n{completed.stdout}\n{completed.stderr}"
        )
    if output.exists() and not preserve_existing:
        raise AssertionError(f"failed invocation published {output}")
    temporary = list(output.parent.glob(f"{output.name}.tmp.qwen-wav.*"))
    if temporary:
        raise AssertionError(f"failed invocation left temporary files: {temporary}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-wav", required=True, type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="qwen_tts_save_wav_safety_") as name:
        root = Path(name)
        success_wav = root / "success.wav"
        success_json = root / "success.json"
        successful = run(
            [
                str(args.save_wav),
                "--mock",
                "--output",
                str(success_wav),
                "--result-json",
                str(success_json),
                "--text",
                "output safety success",
                "--mock-chunks",
                "2",
                "--request-timeout-ms",
                "10000",
            ]
        )
        if successful.returncode != 0:
            raise AssertionError(
                "successful mock synthesis failed:\n"
                f"{successful.stdout}\n{successful.stderr}"
            )
        header = success_wav.read_bytes()[:12]
        if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise AssertionError("successful output is not a RIFF/WAVE file")
        result = json.loads(success_json.read_text(encoding="utf-8"))
        if result.get("terminal_state") != "completed":
            raise AssertionError(f"unexpected result JSON: {result}")

        existing = root / "existing.wav"
        existing.write_bytes(b"sentinel")
        expect_failure(
            [
                str(args.save_wav),
                "--mock",
                "--output",
                str(existing),
                "--text",
                "existing output",
            ],
            existing,
            preserve_existing=True,
        )
        if existing.read_bytes() != b"sentinel":
            raise AssertionError("existing output was modified")

        collision = root / "collision.bin"
        expect_failure(
            [
                str(args.save_wav),
                "--mock",
                "--output",
                str(collision),
                "--result-json",
                str(collision),
                "--text",
                "output collision",
            ],
            collision,
        )

        expect_failure(
            [
                str(args.save_wav),
                "--worker",
                str(root / "missing-worker.exe"),
                "--output",
                str(root / "startup.wav"),
                "--text",
                "startup failure",
            ],
            root / "startup.wav",
        )

        expect_failure(
            [
                str(args.save_wav),
                "--mock",
                "--output",
                str(root / "timeout.wav"),
                "--text",
                "timeout",
                "--mock-chunks",
                "20",
                "--mock-chunk-delay",
                "0.1",
                "--request-timeout-ms",
                "10",
            ],
            root / "timeout.wav",
        )

        expect_failure(
            [
                str(args.save_wav),
                "--worker",
                sys.executable,
                "--worker-arg",
                str(
                    Path(__file__).parents[1]
                    / "acceptance"
                    / "generation_trace_worker.py"
                ),
                "--worker-arg",
                "max_new_tokens",
                "--output",
                str(root / "missing-eos.wav"),
                "--text",
                "missing EOS",
                "--require-natural-eos",
            ],
            root / "missing-eos.wav",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
