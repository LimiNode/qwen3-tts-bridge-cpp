"""Smoke-test strict FasterQwen loading through the bridge Qwen engine."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import threading
from pathlib import Path
from typing import Any

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import QwenTtsEngine, SynthesisRequest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument(
        "--prefill-backend",
        default="compile_reduce_overhead",
        choices=("compile_inductor_default", "compile_reduce_overhead"),
    )
    parser.add_argument("--text", default="I am your robot, I am your worker.")
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--emit-every-frames", type=int, default=8)
    parser.add_argument("--max-chunks", type=int, default=1)
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-max-output-chunks", type=int, default=1)
    parser.add_argument("--forbid-import-path", action="append", default=[])
    parser.add_argument("--wheel-path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = QwenEngineConfig(
        model_path=args.model,
        runtime_backend="faster",
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
        emit_every_frames=args.emit_every_frames,
        prefill_backend=args.prefill_backend,
        prefill_compile_compat_mode="strict_bf16_sdpa_v1",
        warmup_synthesis_enabled=args.warmup_synthesis,
        warmup_max_output_chunks=args.warmup_max_output_chunks,
        warmup_text=args.text,
        warmup_language=args.language,
        warmup_speaker=args.speaker,
        warmup_instruction=args.instruction,
    )
    engine = QwenTtsEngine(config)
    chunks: list[dict[str, Any]] = []
    warmup: dict[str, Any] | None = None
    model: Any | None = None
    metadata_before_warmup: dict[str, Any] | None = None
    metadata_after_request: dict[str, Any] | None = None
    metadata_after_close: dict[str, Any] | None = None
    provenance = _provenance(args)
    _validate_forbidden_import_paths(provenance, args.forbid_import_path)
    try:
        engine.load()
        model = getattr(engine, "_model")
        metadata_before_warmup = _metadata(model)
        warmup = engine.warmup()

        cancel_event = threading.Event()
        stream = engine.synthesize_stream(
            SynthesisRequest(
                request_id=1,
                text=args.text,
                language=args.language,
                speaker=args.speaker,
                instruction=args.instruction,
            ),
            cancel_event,
        )
        try:
            for index, pcm in enumerate(stream, 1):
                chunks.append(
                    {
                        "index": index,
                        "pcm_bytes": len(pcm),
                        "metrics": engine.pop_last_chunk_metrics(),
                    }
                )
                if index >= args.max_chunks:
                    cancel_event.set()
                    break
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        metadata_after_request = _metadata(model)
    finally:
        engine.close()
        if model is not None:
            metadata_after_close = _metadata(model)

    result = {
        "config": {
            "model": args.model,
            "device": args.device,
            "dtype": args.dtype,
            "attn_implementation": args.attn_implementation,
            "prefill_backend": args.prefill_backend,
            "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
            "warmup_synthesis": args.warmup_synthesis,
            "warmup_max_output_chunks": args.warmup_max_output_chunks,
        },
        "provenance": provenance,
        "metadata_before_warmup": metadata_before_warmup,
        "metadata_after_request": metadata_after_request,
        "metadata_after_close": metadata_after_close,
        "cache_stats_after_close": _cache_stats(),
        "warmup": warmup,
        "chunks": chunks,
        "chunk_count": len(chunks),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


def _metadata(model: Any) -> dict[str, Any] | None:
    metadata = getattr(model, "prefill_compile_compat_metadata", None)
    if callable(metadata):
        metadata = metadata()
    if isinstance(metadata, dict):
        return dict(metadata)
    return None


def _provenance(args: argparse.Namespace) -> dict[str, Any]:
    import faster_qwen3_tts

    package_file = str(Path(faster_qwen3_tts.__file__).resolve())
    result: dict[str, Any] = {
        "faster_qwen3_tts_file": package_file,
        "faster_qwen3_tts_version": _distribution_version("faster-qwen3-tts"),
        "faster_qwen3_tts_direct_url": _direct_url("faster-qwen3-tts"),
    }
    if args.wheel_path is not None:
        result["wheel_path"] = str(args.wheel_path)
        result["wheel_sha256"] = _sha256(args.wheel_path)
    return result


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _direct_url(name: str) -> Any:
    try:
        text = importlib.metadata.distribution(name).read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_forbidden_import_paths(
    provenance: dict[str, Any],
    forbidden_paths: list[str],
) -> None:
    package_file = str(provenance.get("faster_qwen3_tts_file", "")).lower()
    for path in forbidden_paths:
        resolved = str(Path(path).resolve()).lower()
        if package_file.startswith(resolved):
            raise RuntimeError(
                "faster_qwen3_tts was imported from a forbidden source path: "
                f"{package_file}"
            )


def _cache_stats() -> dict[str, int] | None:
    try:
        from faster_qwen3_tts.streaming import prefill_compile_cache_stats
    except Exception:
        return None
    return prefill_compile_cache_stats()


if __name__ == "__main__":
    raise SystemExit(main())
