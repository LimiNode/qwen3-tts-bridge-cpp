"""Run the speech-animation acceptance probe against the deterministic worker."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--worker-dir", required=True, type=Path)
    return parser.parse_args()


def run_probe(
    probe: Path,
    python: Path,
    worker_dir: Path,
    adapter: str,
    output: Path,
) -> dict[str, Any]:
    command = [
        str(probe),
        "--adapter",
        adapter,
        "--worker",
        str(python),
        "--worker-arg=-m",
        "--worker-arg=qwen_tts_bridge_worker.main",
        "--worker-arg=--mock",
        "--worker-arg=--mock-chunks",
        "--worker-arg=3",
        "--cwd",
        str(worker_dir),
        "--text",
        "Speech animation probe",
        "--output-json",
        str(output),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(output.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="qtb-speech-animation-") as temporary:
        root = Path(temporary)
        off = run_probe(
            args.probe, args.python, args.worker_dir, "off", root / "off.json"
        )
        on = run_probe(
            args.probe, args.python, args.worker_dir, "on", root / "on.json"
        )

    require(off["success"] is True, "adapter-OFF probe failed")
    require(on["success"] is True, "adapter-ON probe failed")
    require(
        off["pcm_timeline_contiguous"] is True,
        "OFF PCM timeline is not contiguous",
    )
    require(on["pcm_timeline_contiguous"] is True, "ON PCM timeline is not contiguous")
    require(
        on["animation_timeline_contiguous"] is True,
        "animation timeline is not contiguous",
    )
    require(
        on["last_audio_span_matches_pcm_end"] is True,
        "animation does not end at PCM end",
    )
    require(
        on["terminal_fade_anchored_at_pcm_end"] is True,
        "terminal fade is not anchored",
    )
    require(
        on["queue_full_count"] == 0,
        "normal mock run overflowed the animation queue",
    )
    require(on["adapter_callback_count"] == 3, "unexpected adapter callback count")
    require(on["active_span_count"] > 0, "probe produced no active animation spans")
    require(
        on["mouth_open_max"] > on["mouth_open_min"],
        "mouth-open signal did not vary",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
