"""Exercise diagnostic raw PCM capture with the deterministic mock worker."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
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
    wav_output = args.output.with_suffix(".wav")
    wav_output.unlink(missing_ok=True)
    command = [
        str(args.player),
        "--mock",
        "--no-playback",
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

    wav_command = [
        str(args.player),
        "--mock",
        "--no-playback",
        "--text",
        "WAV capture smoke.",
        "--mock-chunks",
        "4",
        "--mock-chunk-ms",
        "150",
        "--wav-capture-file",
        str(wav_output),
    ]
    subprocess.run(wav_command, check=True, timeout=30)
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("verify_wav.py")),
            str(wav_output),
            "--sample-rate",
            "24000",
            "--channels",
            "1",
            "--bits-per-sample",
            "16",
            "--min-data-bytes",
            "1",
        ],
        check=True,
        timeout=30,
    )

    no_tail_wav = args.output.with_name("no-tail.wav")
    no_tail_wav.unlink(missing_ok=True)
    no_tail_command = [
        str(args.player),
        "--mock",
        "--no-playback",
        "--text",
        "No-tail WAV capture smoke.",
        "--mock-chunks",
        "4",
        "--mock-chunk-ms",
        "150",
        "--no-tail",
        "--wav-capture-file",
        str(no_tail_wav),
    ]
    subprocess.run(no_tail_command, check=True, timeout=30)
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("verify_wav.py")),
            str(no_tail_wav),
            "--sample-rate",
            "24000",
            "--channels",
            "1",
            "--bits-per-sample",
            "16",
            "--min-data-bytes",
            str(expected_bytes),
        ],
        check=True,
        timeout=30,
    )
    with wave.open(str(no_tail_wav), "rb") as reader:
        no_tail_pcm = reader.readframes(reader.getnframes())
    assert no_tail_pcm == args.output.read_bytes()

    tail_wav = args.output.with_name("tail.wav")
    tail_wav.unlink(missing_ok=True)
    tail_command = [
        str(args.player),
        "--mock",
        "--no-playback",
        "--text",
        "Tail WAV capture smoke.",
        "--mock-chunks",
        "4",
        "--mock-chunk-ms",
        "150",
        "--tail",
        "--wav-capture-file",
        str(tail_wav),
    ]
    subprocess.run(tail_command, check=True, timeout=30)
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("verify_wav.py")),
            str(tail_wav),
            "--sample-rate",
            "24000",
            "--channels",
            "1",
            "--bits-per-sample",
            "16",
            "--min-data-bytes",
            str(expected_bytes),
        ],
        check=True,
        timeout=30,
    )
    with wave.open(str(tail_wav), "rb") as reader:
        tail_pcm = reader.readframes(reader.getnframes())
    raw_frames = expected_bytes // 2
    fade_frames = 24_000 * 15 // 1_000
    silence_frames = 24_000 * 85 // 1_000
    assert len(tail_pcm) == (raw_frames + silence_frames) * 2
    assert tail_pcm[: (raw_frames - fade_frames) * 2] == args.output.read_bytes()[:
        (raw_frames - fade_frames) * 2
    ]

    duplicate_wav = subprocess.run(wav_command, capture_output=True, text=True)
    assert duplicate_wav.returncode != 0
    assert "refusing to overwrite existing WAV capture file" in duplicate_wav.stderr

    raw_named_wav = args.output.with_name("raw-named.wav")
    remove_capture(raw_named_wav)
    raw_command = [*command]
    output_index = raw_command.index(str(args.output))
    raw_command[output_index] = str(raw_named_wav)
    subprocess.run(raw_command, check=True, timeout=30)
    mislabeled = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("verify_wav.py")),
            str(raw_named_wav),
            "--sample-rate",
            "24000",
            "--channels",
            "1",
            "--bits-per-sample",
            "16",
        ],
        capture_output=True,
        text=True,
    )
    assert mislabeled.returncode != 0

    wrong_format = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("verify_wav.py")),
            str(wav_output),
            "--sample-rate",
            "16000",
            "--channels",
            "1",
            "--bits-per-sample",
            "16",
        ],
        capture_output=True,
        text=True,
    )
    assert wrong_format.returncode != 0

    invalid_channels = subprocess.run(
        [
            str(args.player),
            "--mock",
            "--channels",
            "0",
            "--text",
            "Invalid WAV format.",
            "--wav-capture-file",
            str(args.output.with_name("invalid.wav")),
        ],
        capture_output=True,
        text=True,
    )
    assert invalid_channels.returncode != 0
    assert "invalid requested PCM format" in invalid_channels.stderr

    interactive_wav = subprocess.run(
        [str(args.player), "--mock", "--wav-capture-file", str(wav_output)],
        capture_output=True,
        text=True,
    )
    assert interactive_wav.returncode != 0
    assert "requires one-shot --text playback" in interactive_wav.stderr
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
