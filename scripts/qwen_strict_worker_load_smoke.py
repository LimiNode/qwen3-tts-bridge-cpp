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
    parser.add_argument(
        "--prefill-compile-lengths",
        type=_parse_prefill_compile_lengths,
        default=(),
    )
    parser.add_argument(
        "--no-prefill-compile-on-miss",
        action="store_false",
        dest="prefill_compile_on_miss",
        default=True,
    )
    parser.add_argument(
        "--prefill-unknown-shape-policy",
        choices=("eager", "error"),
        default="eager",
    )
    parser.add_argument(
        "--prefill-compile-policy",
        choices=("diagnostic_dynamic", "exact_allowlist"),
        default="diagnostic_dynamic",
    )
    parser.add_argument("--prefill-allowlist-warmup-manifest", default="")
    parser.add_argument("--prefill-allowlist-warmup-repeats", type=int, default=3)
    parser.add_argument("--prefill-allowlist-max-entries", type=int, default=6)
    parser.add_argument(
        "--prefill-allowlist-max-abs-threshold",
        type=float,
        default=0.0,
    )
    parser.add_argument("--prefill-require-precompiled", action="store_true")
    parser.add_argument("--prefill-first-chunk-warmup", action="store_true")
    parser.add_argument("--prefill-first-chunk-warmup-length", type=int, default=None)
    parser.add_argument("--text", default="I am your robot, I am your worker.")
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--emit-every-frames", type=int, default=8)
    parser.add_argument("--max-chunks", type=int, default=1)
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-max-output-chunks", type=int, default=1)
    parser.add_argument("--max-generation-state-wall-ms", type=float, default=5.0)
    parser.add_argument("--max-compiled-prefill-ms", type=float, default=25.0)
    parser.add_argument(
        "--max-first-chunk-wall-ms",
        type=float,
        default=0.0,
        help="Optional first PCM wall-time gate; 0 disables this check.",
    )
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
        prefill_compile_lengths=args.prefill_compile_lengths,
        prefill_compile_on_miss=args.prefill_compile_on_miss,
        prefill_unknown_shape_policy=args.prefill_unknown_shape_policy,
        prefill_compile_policy=args.prefill_compile_policy,
        prefill_allowlist_warmup_manifest=args.prefill_allowlist_warmup_manifest,
        prefill_allowlist_warmup_repeats=args.prefill_allowlist_warmup_repeats,
        prefill_allowlist_max_entries=args.prefill_allowlist_max_entries,
        prefill_allowlist_max_abs_threshold=(
            args.prefill_allowlist_max_abs_threshold
        ),
        prefill_require_precompiled=args.prefill_require_precompiled,
        prefill_first_chunk_warmup_enabled=args.prefill_first_chunk_warmup,
        prefill_first_chunk_warmup_length=args.prefill_first_chunk_warmup_length,
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
    cache_stats_after_request: dict[str, Any] | None = None
    provenance = _provenance(args)
    _validate_forbidden_import_paths(provenance, args.forbid_import_path)
    try:
        engine.load()
        model = engine._model
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
        cache_stats_after_request = _cache_stats()
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
            "prefill_compile_lengths": args.prefill_compile_lengths,
            "prefill_compile_on_miss": args.prefill_compile_on_miss,
            "prefill_unknown_shape_policy": args.prefill_unknown_shape_policy,
            "prefill_compile_policy": args.prefill_compile_policy,
            "prefill_allowlist_warmup_manifest": (
                args.prefill_allowlist_warmup_manifest
            ),
            "prefill_allowlist_warmup_repeats": (
                args.prefill_allowlist_warmup_repeats
            ),
            "prefill_require_precompiled": args.prefill_require_precompiled,
            "prefill_first_chunk_warmup": args.prefill_first_chunk_warmup,
            "prefill_first_chunk_warmup_length": args.prefill_first_chunk_warmup_length,
            "warmup_synthesis": args.warmup_synthesis,
            "warmup_max_output_chunks": args.warmup_max_output_chunks,
        },
        "provenance": provenance,
        "metadata_before_warmup": metadata_before_warmup,
        "metadata_after_request": metadata_after_request,
        "metadata_after_close": metadata_after_close,
        "cache_stats_after_request": cache_stats_after_request,
        "cache_stats_after_close": _cache_stats(),
        "cuda_memory_after_close": _cuda_memory_stats(),
        "warmup": warmup,
        "chunks": chunks,
        "chunk_count": len(chunks),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    _validate_result(result, args)
    return 0


def _metadata(model: Any) -> dict[str, Any] | None:
    metadata = getattr(model, "prefill_compile_compat_metadata", None)
    if callable(metadata):
        metadata = metadata()
    if isinstance(metadata, dict):
        return dict(metadata)
    return None


def _parse_prefill_compile_lengths(value: str) -> tuple[int, ...]:
    text = value.strip()
    if not text:
        return ()
    lengths: list[int] = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must not contain empty items"
            )
        try:
            length = int(item)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must contain integers"
            ) from exc
        if length <= 0:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must contain positive integers"
            )
        lengths.append(length)
    if len(set(lengths)) != len(lengths):
        raise argparse.ArgumentTypeError(
            "--prefill-compile-lengths must not contain duplicates"
        )
    return tuple(lengths)


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


def _cache_stats() -> dict[str, Any] | None:
    try:
        from faster_qwen3_tts.streaming import prefill_compile_cache_stats
    except Exception:
        return None
    return prefill_compile_cache_stats()


def _cuda_memory_stats() -> dict[str, int] | None:
    try:
        import torch
    except Exception:
        return None
    if not torch.cuda.is_available():
        return None
    return {
        "allocated_bytes": int(torch.cuda.memory_allocated()),
        "reserved_bytes": int(torch.cuda.memory_reserved()),
        "max_reserved_bytes": int(torch.cuda.max_memory_reserved()),
    }


def _validate_result(result: dict[str, Any], args: argparse.Namespace) -> None:
    provenance = result["provenance"]
    if args.wheel_path is not None:
        expected_sha = str(provenance["wheel_sha256"]).lower()
        direct_url_sha = _direct_url_sha256(
            provenance.get("faster_qwen3_tts_direct_url")
        )
        if direct_url_sha != expected_sha:
            raise RuntimeError(
                "installed faster_qwen3_tts archive SHA does not match wheel: "
                f"installed={direct_url_sha!r}, wheel={expected_sha!r}"
            )

    if result["chunk_count"] <= 0:
        raise RuntimeError("strict worker smoke produced no audio chunks")
    first_metrics = result["chunks"][0].get("metrics") or {}
    if first_metrics.get("prefill_backend_used") != args.prefill_backend:
        raise RuntimeError(
            "strict worker smoke used unexpected prefill backend: "
            f"{first_metrics.get('prefill_backend_used')!r}"
        )
    if first_metrics.get("prefill_compile_fallback") is not False:
        raise RuntimeError(
            "strict worker smoke fell back from compiled prefill: "
            f"{first_metrics.get('prefill_compile_error')!r}"
        )
    if first_metrics.get("prefill_compile_cache_kind") != "python_callable_lru":
        raise RuntimeError(
            "strict worker smoke reported unexpected compile cache kind: "
            f"{first_metrics.get('prefill_compile_cache_kind')!r}"
        )
    if args.prefill_compile_lengths:
        if first_metrics.get("prefill_shape_allowlist_hit") is not True:
            raise RuntimeError(
                "strict worker smoke did not hit the configured prefill "
                f"allowlist: {first_metrics!r}"
            )
        if first_metrics.get("prefill_shape_policy") != "compiled_allowlist":
            raise RuntimeError(
                "strict worker smoke used unexpected shape policy: "
                f"{first_metrics.get('prefill_shape_policy')!r}"
            )
    if args.prefill_compile_policy == "exact_allowlist":
        _validate_exact_allowlist_result(result, args, first_metrics)
    cache_after_request = result.get("cache_stats_after_request")
    if not isinstance(cache_after_request, dict):
        raise RuntimeError("strict worker smoke did not report request cache stats")
    if cache_after_request.get("entries", 0) < 1:
        raise RuntimeError(
            "strict worker smoke did not populate Python callable cache: "
            f"{cache_after_request!r}"
        )
    for key in (
        "prefill_cuda_memory_before_allocated_bytes",
        "prefill_cuda_memory_before_reserved_bytes",
        "prefill_cuda_memory_after_allocated_bytes",
        "prefill_cuda_memory_after_reserved_bytes",
    ):
        if key not in first_metrics:
            raise RuntimeError(f"strict worker smoke missing CUDA memory field {key}")
    for label in ("metadata_after_request", "metadata_after_close"):
        _validate_idle_metadata(label, result.get(label))
    cache_after_close = result.get("cache_stats_after_close") or {}
    if cache_after_close.get("entries") != 0:
        raise RuntimeError(
            "strict worker smoke left Python callable cache entries after close: "
            f"{cache_after_close!r}"
        )


def _validate_exact_allowlist_result(
    result: dict[str, Any],
    args: argparse.Namespace,
    first_metrics: dict[str, Any],
) -> None:
    warmup = result.get("warmup")
    if not isinstance(warmup, dict):
        raise RuntimeError("exact allowlist smoke did not report warmup fields")
    if warmup.get("prefill_allowlist_ready") is not True:
        raise RuntimeError(
            "exact allowlist smoke did not prewarm allowlisted shapes before ready"
        )
    if warmup.get("prefill_decode_state_ready") is not True:
        raise RuntimeError(
            "exact allowlist smoke did not prewarm decode state before ready"
        )
    if (
        args.prefill_first_chunk_warmup
        and warmup.get("prefill_first_chunk_warmup_ready") is not True
    ):
        raise RuntimeError(
            "exact allowlist smoke did not prewarm the first chunk before ready"
        )
    if list(warmup.get("prefill_allowlist_lengths") or []) != list(
        args.prefill_compile_lengths
    ):
        raise RuntimeError(
            "exact allowlist smoke reported unexpected warmup lengths: "
            f"{warmup.get('prefill_allowlist_lengths')!r}"
        )
    rows = warmup.get("prefill_allowlist_warmup_passes")
    if not isinstance(rows, list) or len(rows) != len(args.prefill_compile_lengths):
        raise RuntimeError(
            "exact allowlist smoke did not report one warmup row per length"
        )
    min_ordinal = min(
        int(row.get("prefill_shape_call_ordinal", 0))
        for row in rows
        if isinstance(row, dict)
    )
    if min_ordinal < args.prefill_allowlist_warmup_repeats:
        raise RuntimeError(
            "exact allowlist warmup did not reach the configured repeat count: "
            f"min_ordinal={min_ordinal}"
        )
    if first_metrics.get("prefill_require_precompiled") is not True:
        raise RuntimeError(
            "exact allowlist first request did not run with require_precompiled=true"
        )
    if int(first_metrics.get("prefill_shape_call_ordinal", 0)) < (
        args.prefill_allowlist_warmup_repeats + 1
    ):
        raise RuntimeError(
            "exact allowlist first request did not use a prewarmed compiled entry: "
            f"{first_metrics!r}"
        )
    if first_metrics.get("generation_state_mask_cache_hit") is not True:
        raise RuntimeError(
            "exact allowlist first request missed generation mask cache: "
            f"{first_metrics!r}"
        )
    if int(first_metrics.get("generation_state_masks_built", 0)) != 0:
        raise RuntimeError(
            "exact allowlist first request rebuilt generation masks: "
            f"{first_metrics!r}"
        )
    _require_metric_below(
        first_metrics,
        "prefill_compiled_call_3plus_host_ms",
        args.max_compiled_prefill_ms,
    )
    _require_metric_below(
        first_metrics,
        "generation_state_wall_ms",
        args.max_generation_state_wall_ms,
    )
    if args.max_first_chunk_wall_ms > 0.0:
        _require_metric_below(
            first_metrics,
            "next_wall_ms",
            args.max_first_chunk_wall_ms,
        )


def _require_metric_below(
    metrics: dict[str, Any],
    key: str,
    threshold: float,
) -> None:
    value = metrics.get(key)
    if not isinstance(value, (int, float)):
        raise RuntimeError(f"exact allowlist smoke missing numeric metric {key}")
    if float(value) >= threshold:
        raise RuntimeError(
            f"exact allowlist smoke metric {key}={value} exceeds "
            f"threshold {threshold}"
        )


def _direct_url_sha256(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    archive = value.get("archive_info")
    if not isinstance(archive, dict):
        return None
    hashes = archive.get("hashes")
    if isinstance(hashes, dict) and hashes.get("sha256"):
        return str(hashes["sha256"]).lower()
    digest = archive.get("hash")
    if isinstance(digest, str) and digest.startswith("sha256="):
        return digest.removeprefix("sha256=").lower()
    return None


def _validate_idle_metadata(label: str, metadata: Any) -> None:
    if not isinstance(metadata, dict):
        raise RuntimeError(f"{label} is missing strict compat metadata")
    if metadata.get("prefill_compile_compat_applied") is not False:
        raise RuntimeError(f"{label} reports active strict patch")
    if metadata.get("prefill_compile_compat_patched_modules") != {}:
        raise RuntimeError(f"{label} reports patched modules after request")
    validated = metadata.get("prefill_compile_compat_validated_modules")
    if not isinstance(validated, dict) or not validated:
        raise RuntimeError(f"{label} missing validated module counts")


if __name__ == "__main__":
    raise SystemExit(main())
