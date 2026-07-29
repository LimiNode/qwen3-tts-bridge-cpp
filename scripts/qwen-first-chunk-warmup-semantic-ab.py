"""Compare fresh-process CustomVoice output with first-chunk warmup on and off."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Event
from typing import Any

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import AudioFormat, QwenTtsEngine, SynthesisRequest
from faster_qwen_provenance import load_faster_qwen_provenance
from semantic_trace_contract import validate_generation_trace


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
    "hit_eos",
    "hit_max_new_tokens",
    "hit_max_seq_len",
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
    parser.add_argument("--no-user-reseed", action="store_true")
    parser.add_argument("--faster-qwen-provenance", type=Path, required=True)
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
    faster_provenance = load_faster_qwen_provenance(args.faster_qwen_provenance)

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
        "schema_version": 2,
        "sampling_count": args.sampling_count,
        "no_user_reseed": args.no_user_reseed,
        "faster_qwen_provenance": faster_provenance,
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
        "--faster-qwen-provenance",
        str(args.faster_qwen_provenance),
    ]
    if no_sample:
        command.append("--no-sample")
    if first_chunk_warmup:
        command.append("--first-chunk-warmup")
    if args.no_user_reseed:
        command.append("--no-user-reseed")
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
        seed=None if args.no_user_reseed else args.seed,
        seed_mode="fixed",
    )
    engine = QwenTtsEngine(config)
    try:
        engine.load()
        if args.no_user_reseed:
            _seed_all_rngs(args.seed)
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
        validate_generation_trace(trace)
        pcm = b"".join(pcm_chunks)
        provenance = {
            **_wheel_provenance(args.faster_qwen_provenance),
            **_runtime_provenance(
                str(
                    load_faster_qwen_provenance(args.faster_qwen_provenance)[
                        "source_commit"
                    ]
                )
            ),
        }
        report: dict[str, Any] = {
            "seed": args.seed,
            "do_sample": not args.no_sample,
            "user_reseed": not args.no_user_reseed,
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
            "hit_eos": trace["hit_eos"],
            "hit_max_new_tokens": trace["hit_max_new_tokens"],
            "hit_max_seq_len": trace["hit_max_seq_len"],
            **provenance,
        }
    finally:
        engine.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _seed_all_rngs(seed: int) -> None:
    random.seed(seed)
    numpy = importlib.import_module("numpy")
    numpy.random.seed(seed % (2**32))
    torch = importlib.import_module("torch")
    if not torch.cuda.is_available():
        raise RuntimeError("no-user-reseed semantic A/B requires CUDA")
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _wheel_provenance(provenance_path: Path) -> dict[str, object]:
    provenance = load_faster_qwen_provenance(provenance_path)
    expected = str(provenance["wheel_sha256"])
    distribution = importlib.metadata.distribution("faster-qwen3-tts")
    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text is None:
        raise RuntimeError("installed FasterQwen wheel has no direct_url.json")
    direct_url = json.loads(direct_url_text)
    actual = str(direct_url.get("archive_info", {}).get("hash", ""))
    actual = actual.removeprefix("sha256=").lower()
    if not actual:
        raise RuntimeError("installed FasterQwen wheel direct URL has no SHA-256")
    if actual != expected:
        raise RuntimeError(
            "installed FasterQwen wheel SHA-256 mismatch: "
            f"expected={expected}, actual={actual}"
        )
    return {
        "faster_qwen3_tts_file": str(
            importlib.import_module("faster_qwen3_tts").__file__
        ),
        "faster_qwen3_tts_version": distribution.version,
        "faster_qwen3_tts_wheel_sha256": actual,
        "faster_qwen3_tts_wheel_match_verified": True,
        "faster_qwen3_tts_source_commit": provenance["source_commit"],
        "faster_qwen3_tts_bundle_sha256": provenance["bundle_sha256"],
        "faster_qwen_provenance_manifest": str(provenance_path),
        "faster_qwen_provenance_manifest_sha256": provenance["manifest_sha256"],
    }


def _runtime_provenance(faster_qwen_commit: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    qwen_root = root / "external" / "python" / "Qwen3-TTS-streaming"
    torch = importlib.import_module("torch")
    if not torch.cuda.is_available():
        raise RuntimeError("semantic A/B requires CUDA runtime provenance")

    driver = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=driver_version",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().splitlines()
    if not driver:
        raise RuntimeError("nvidia-smi did not return a driver version")

    return {
        "bridge_commit": _git_revision(root),
        "faster_qwen3_tts_commit": faster_qwen_commit,
        "qwen3_tts_streaming_commit": _git_revision(qwen_root),
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0),
        "nvidia_driver_version": driver[0],
    }


def _git_revision(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    main()
