"""Compare fresh-process CustomVoice output with first-chunk warmup on and off."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Event
from typing import Any

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import AudioFormat, QwenTtsEngine, SynthesisRequest


TRACE_KEYS = (
    "pcm_sha256",
    "sample_count",
    "chunk_count",
    "codec_sha256",
    "codec_frame_count",
    "termination_reason",
    "terminal_token_id",
    "terminal_step_index",
    "generated_steps",
    "emitted_steps",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--compile-lengths", default="32,29,35,34,33,30")
    parser.add_argument("--warmup-length", type=int, default=32)
    parser.add_argument(
        "--text",
        default="In a relaxed tone, say: Measure the first chunk, the total duration, and the real time factor.",
    )
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--sampling-count", type=int, default=20)
    parser.add_argument("--first-chunk-warmup", action="store_true")
    parser.add_argument("--no-sample", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.child:
        _run_child(args)
        return
    _run_parent(args)


def _run_parent(args: argparse.Namespace) -> None:
    if args.sampling_count <= 0:
        raise ValueError("--sampling-count must be positive")

    scenarios = [("greedy", args.seed, True)]
    scenarios.extend(
        ("sampling", args.seed + offset, False)
        for offset in range(args.sampling_count)
    )
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="qtb-semantic-ab-") as temporary:
        temporary_path = Path(temporary)
        for kind, seed, no_sample in scenarios:
            off = _run_child_process(
                args,
                output_path=temporary_path / f"{kind}-{seed}-off.json",
                seed=seed,
                no_sample=no_sample,
                first_chunk_warmup=False,
            )
            on = _run_child_process(
                args,
                output_path=temporary_path / f"{kind}-{seed}-on.json",
                seed=seed,
                no_sample=no_sample,
                first_chunk_warmup=True,
            )
            mismatches = {
                key: {"without_warmup": off.get(key), "with_warmup": on.get(key)}
                for key in TRACE_KEYS
                if off.get(key) != on.get(key)
            }
            results.append(
                {
                    "kind": kind,
                    "seed": seed,
                    "semantic_pass": not mismatches,
                    "mismatches": mismatches,
                    "without_warmup": off,
                    "with_warmup": on,
                }
            )

    report = {
        "schema_version": 1,
        "sampling_count": args.sampling_count,
        "trace_keys": list(TRACE_KEYS),
        "semantic_pass": all(row["semantic_pass"] for row in results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"semantic_pass": report["semantic_pass"], "output": str(args.output)}))
    if not report["semantic_pass"]:
        raise SystemExit(1)


def _run_child_process(
    args: argparse.Namespace,
    *,
    output_path: Path,
    seed: int,
    no_sample: bool,
    first_chunk_warmup: bool,
) -> dict[str, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--output",
        str(output_path),
        "--model",
        str(args.model),
        "--manifest",
        str(args.manifest),
        "--compile-lengths",
        args.compile_lengths,
        "--warmup-length",
        str(args.warmup_length),
        "--text",
        args.text,
        "--language",
        args.language,
        "--speaker",
        args.speaker,
        "--seed",
        str(seed),
        "--sampling-count",
        "1",
    ]
    if no_sample:
        command.append("--no-sample")
    if first_chunk_warmup:
        command.append("--first-chunk-warmup")
    subprocess.run(command, check=True)
    return json.loads(output_path.read_text(encoding="utf-8"))


def _run_child(args: argparse.Namespace) -> None:
    lengths = tuple(int(value) for value in args.compile_lengths.split(",") if value)
    config = QwenEngineConfig(
        model_path=str(args.model),
        runtime_backend="faster",
        device="cuda",
        dtype="bfloat16",
        attn_implementation="sdpa",
        emit_every_frames=8,
        decode_window_frames=80,
        prefill_backend="compile_reduce_overhead",
        prefill_compile_compat_mode="strict_bf16_sdpa_v1",
        prefill_compile_lengths=lengths,
        prefill_compile_on_miss=False,
        prefill_unknown_shape_policy="eager",
        prefill_compile_policy="exact_allowlist",
        prefill_allowlist_warmup_manifest=str(args.manifest),
        prefill_require_precompiled=True,
        prefill_first_chunk_warmup_enabled=args.first_chunk_warmup,
        prefill_first_chunk_warmup_length=(
            args.warmup_length if args.first_chunk_warmup else None
        ),
        do_sample=not args.no_sample,
        seed=args.seed,
        seed_mode="fixed",
    )
    engine = QwenTtsEngine(config)
    try:
        engine.load()
        engine.warmup()
        model = engine._require_model()
        if not hasattr(model, "collect_generation_trace"):
            raise RuntimeError("installed FasterQwen wheel lacks generation trace support")
        model.collect_generation_trace = True
        pcm_chunks = list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text=args.text,
                    language=args.language,
                    speaker=args.speaker,
                    output=AudioFormat.default(),
                ),
                Event(),
            )
        )
        trace = getattr(model, "last_generation_trace", None)
        if not isinstance(trace, dict):
            raise RuntimeError("FasterQwen did not produce a generation trace")
        pcm = b"".join(pcm_chunks)
        distribution = importlib.metadata.distribution("faster-qwen3-tts")
        report: dict[str, Any] = {
            "seed": args.seed,
            "do_sample": not args.no_sample,
            "first_chunk_warmup": args.first_chunk_warmup,
            "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
            "sample_count": len(pcm) // 2,
            "chunk_count": len(pcm_chunks),
            "codec_sha256": trace["codec_sha256"],
            "codec_frame_count": trace["codec_frame_count"],
            "termination_reason": trace["termination_reason"],
            "terminal_token_id": trace["terminal_token_id"],
            "terminal_step_index": trace["terminal_step_index"],
            "generated_steps": trace["generated_steps"],
            "emitted_steps": trace["emitted_steps"],
            "faster_qwen3_tts_file": str(importlib.import_module("faster_qwen3_tts").__file__),
            "faster_qwen3_tts_version": distribution.version,
        }
    finally:
        engine.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
