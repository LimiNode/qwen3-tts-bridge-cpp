"""Exercise opt-in sentence streaming through the real player and mock worker."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import wave
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Keep a stuck C++/worker pair from blocking the outer CTest indefinitely."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        else:
            process.kill()
        process.communicate(timeout=5)
        raise
    return subprocess.CompletedProcess(
        command, process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=args.output_root, prefix="segmented-"
    ) as temporary:
        root = Path(temporary)
        common = [
            str(args.player), "--mock", "--mock-playback-sink", "--no-tts-front",
            "--no-tail", "--segment-text", "--mock-chunks", "2",
            "--mock-chunk-ms", "20",
        ]
        wav = root / "complete.wav"
        text = "В мастерско\u0301й тихо. Инженер проверил USB-порт."
        result = run(common + ["--text", text, "--wav-capture-file", str(wav)])
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert output.count("speech_segment index=") == 2, output
        epochs = [
            line.split(" playback_epoch=")[1]
            for line in output.splitlines()
            if line.startswith("speech_segment request_id=")
        ]
        assert len(epochs) == 2 and len(set(epochs)) == 1, output
        assert "speech_segment index=0 count=2 source_begin=0" in output, output
        assert "text_front effective=В мастерско\u0301й тихо. " in output, output
        assert "text_front effective=Инженер проверил USB-порт." in output, output
        with wave.open(str(wav), "rb") as audio:
            assert (
                audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
            ) == (24000, 1, 2)
            assert audio.getnframes() == 2 * 2 * 20 * 24000 // 1000
            assert len(audio.readframes(audio.getnframes())) == audio.getnframes() * 2

        failed = root / "failed.wav"
        result = run(common + [
            "--text", "First. Second. Third.", "--wav-capture-file", str(failed),
            "--mock-playback-fail-after", "2",
        ])
        output = result.stdout + result.stderr
        assert result.returncode != 0, output
        assert "playback failed" in output, output
        assert "speech_segment index=2" not in output, output
        assert not failed.exists(), "failed segmented result published a final WAV"
        assert not list(root.glob("failed.wav.tmp.*")), "failed capture left temporary"

        timed_out = root / "timed-out.wav"
        result = run(common + [
            "--text", "First. Second. Third.", "--wav-capture-file", str(timed_out),
            "--request-timeout-ms", "70", "--mock-chunk-delay", "0.03",
        ])
        output = result.stdout + result.stderr
        assert result.returncode != 0 and "timed out" in output, output
        assert "speech_segment index=2" not in output, output
        assert not timed_out.exists(), "deadline failure published a final WAV"
        assert not list(root.glob("timed-out.wav.tmp.*")), "timeout left a temporary"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
