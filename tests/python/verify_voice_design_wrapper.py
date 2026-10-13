"""Exercise the VoiceDesign PowerShell wrapper with a real C++ mock path."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wrapper", required=True, type=Path)
    parser.add_argument("--save-wav", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--worker-dir", required=True, type=Path)
    parser.add_argument("--capture-worker", required=True, type=Path)
    return parser.parse_args()


def run_powershell(
    arguments: list[str], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def write_corrupt_save_wav(directory: Path, python: Path) -> Path:
    helper = directory / "write_corrupt_wav.py"
    helper.write_text(
        '''import json, pathlib, sys
args = sys.argv[1:]
out = pathlib.Path(args[args.index("--output") + 1])
result = pathlib.Path(args[args.index("--result-json") + 1])
out.write_bytes(
    b"RIFF\\x64\\x00\\x00\\x00WAVEfmt \\x10\\x00\\x00\\x00"
    + b"\\x01\\x00\\x01\\x00\\xc0\\x5d\\x00\\x00\\x00\\x00\\x00\\x00"
    + b"\\x02\\x00\\x10\\x00data\\x10\\x00\\x00\\x00\\x00\\x00"
)
result.write_text(
    json.dumps({"terminal_state": "completed", "audio_bytes": 16}),
    encoding="utf-8",
)
''',
        encoding="utf-8",
    )
    command = directory / "write_corrupt_wav.cmd"
    command.write_text(
        f'@"{python}" "%~dp0{helper.name}" %*\r\n',
        encoding="ascii",
    )
    return command


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("VoiceDesign wrapper regression requires Windows PowerShell")
    args = parse_args()
    text = "Сегодня голос говорит спокойно."
    instruction = "Тёплый русский голос, мягко и выразительно."

    with tempfile.TemporaryDirectory(prefix="qtb-voice-design-wrapper-") as temporary:
        root = Path(temporary)
        output = root / "voice-design.wav"
        result = root / "voice-design.json"
        capture = root / "capture.json"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(args.worker_dir / "src")
        env["QTB_UTF8_CAPTURE_PATH"] = str(capture)

        positive = run_powershell(
            [
                str(args.wrapper),
                "-SaveWavExecutable",
                str(args.save_wav),
                "-Worker",
                str(args.python),
                "-WorkerArgument",
                "-B",
                str(args.capture_worker),
                "-Text",
                text,
                "-Instruction",
                instruction,
                "-Language",
                "Russian",
                "-Output",
                str(output),
                "-ResultJson",
                str(result),
            ],
            env,
        )
        require(
            positive.returncode == 0,
            "positive VoiceDesign wrapper run failed:\n"
            + positive.stdout
            + positive.stderr,
        )
        captured = json.loads(capture.read_text(encoding="utf-8"))
        require(captured["text"] == text, "worker text was not preserved as UTF-8")
        require(
            captured["instruction"] == instruction,
            "worker instruction was not preserved as UTF-8",
        )
        require(
            bytes.fromhex(captured["text_utf8"]) == text.encode("utf-8"),
            "worker text UTF-8 bytes changed",
        )
        require(
            bytes.fromhex(captured["instruction_utf8"])
            == instruction.encode("utf-8"),
            "worker instruction UTF-8 bytes changed",
        )

        corrupt_save_wav = write_corrupt_save_wav(root, args.python)
        negative = run_powershell(
            [
                str(args.wrapper),
                "-SaveWavExecutable",
                str(corrupt_save_wav),
                "-Worker",
                str(args.python),
                "-Text",
                text,
                "-Instruction",
                instruction,
                "-Output",
                str(root / "corrupt.wav"),
                "-ResultJson",
                str(root / "corrupt.json"),
            ],
            env,
        )
        require(
            negative.returncode != 0,
            "wrapper accepted a physically truncated/corrupt WAV",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
