"""Command-line parsing and worker configuration construction."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeVar, cast

from qwen_tts_bridge_worker.config import (
    CanaryRuntimeProvenance,
    EngineConfig,
    MockEngineConfig,
    QwenEngineConfig,
    WorkerConfig,
)

T = TypeVar("T")


def build_parser() -> argparse.ArgumentParser:
    """Build the worker command-line parser."""

    parser = argparse.ArgumentParser(description="QwenTTSBridge Python worker")

    _add_root_server_options(parser)

    _add_legacy_engine_options(parser)

    subparsers = parser.add_subparsers(
        dest="engine_command",
        metavar="engine",
    )
    server_options = _server_options_parent_parser()
    _add_mock_subcommand(subparsers, server_options)
    _add_qwen_subcommand(subparsers, server_options)
    return parser


def build_worker_config(args: argparse.Namespace) -> WorkerConfig:
    """Build a validated worker configuration from parsed arguments."""

    engine = build_engine_config(args)
    return WorkerConfig(
        worker_version=_selected_worker_version(args),
        output_queue_size=_selected_output_queue_size(args),
        engine_startup_mode=_selected_engine_startup_mode(args, engine),
        engine=engine,
        canary_runtime_provenance=_build_canary_runtime_provenance(args, engine),
    )


def _build_canary_runtime_provenance(
    args: argparse.Namespace,
    engine: EngineConfig,
) -> CanaryRuntimeProvenance | None:
    runtime_profile_path = _selected_server_option(
        args.root_canary_runtime_profile_manifest,
        getattr(args, "command_canary_runtime_profile_manifest", None),
        "canary-runtime-profile-manifest",
        None,
    )
    allowlist_path = _selected_server_option(
        args.root_canary_compiled_allowlist_manifest,
        getattr(args, "command_canary_compiled_allowlist_manifest", None),
        "canary-compiled-allowlist-manifest",
        None,
    )
    if runtime_profile_path is None and allowlist_path is None:
        return None
    if runtime_profile_path is None or allowlist_path is None:
        raise ValueError(
            "--canary-runtime-profile-manifest and "
            "--canary-compiled-allowlist-manifest must be used together"
        )
    if not isinstance(engine, QwenEngineConfig):
        raise ValueError("canary runtime provenance requires the qwen engine")
    runtime_profile = _load_manifest(runtime_profile_path, "runtime profile")
    allowlist = _load_manifest(allowlist_path, "compiled allowlist")
    provenance = CanaryRuntimeProvenance.from_manifests(
        runtime_profile,
        allowlist,
        sha256(allowlist_path.read_bytes()).hexdigest(),
    )
    if tuple(sorted(engine.prefill_compile_lengths)) != provenance.compiled_lengths:
        raise ValueError("worker compiled lengths do not match allowlist manifest")
    if engine.compiled_emit_chunk_schedule != (8, 8, 12):
        raise ValueError("canary provenance requires compiled 8,8,12 schedule")
    if engine.eager_emit_chunk_schedule != (8,):
        raise ValueError("canary provenance requires eager fixed-8 schedule")
    if engine.prefill_compile_policy != "exact_allowlist":
        raise ValueError("canary provenance requires exact allowlist policy")
    if engine.prefill_compile_on_miss or not engine.prefill_require_precompiled:
        raise ValueError("canary provenance requires precompiled no-miss policy")
    return provenance


def _load_manifest(path: Path, name: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {name} manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} manifest is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} manifest must contain an object")
    return value


def build_engine_config(args: argparse.Namespace) -> EngineConfig:
    """Build the selected engine configuration from parsed arguments."""

    engine_command = getattr(args, "engine_command", None)
    if engine_command is not None:
        _reject_mixed_legacy_engine_flags(args)
        if engine_command == "mock":
            return MockEngineConfig(
                chunk_count=args.mock_chunks,
                chunk_duration_ms=args.mock_chunk_ms,
                chunk_delay_seconds=args.mock_chunk_delay,
            )
        if engine_command == "qwen":
            return QwenEngineConfig(
                model_path=args.model_path,
                runtime_backend=args.runtime_backend,
                device=args.device,
                dtype=args.dtype,
                attn_implementation=args.attn_implementation,
                max_seq_len=args.max_seq_len,
                max_audio_seconds_per_utterance=(
                    args.max_audio_seconds_per_utterance
                ),
                emit_every_frames=args.emit_every_frames,
                emit_chunk_schedule=args.emit_chunk_schedule,
                compiled_emit_chunk_schedule=args.compiled_emit_chunk_schedule,
                eager_emit_chunk_schedule=args.eager_emit_chunk_schedule,
                decode_window_frames=args.decode_window_frames,
                overlap_samples=args.overlap_samples,
                enable_streaming_optimizations=args.enable_streaming_optimizations,
                use_compile=not args.no_compile,
                use_cuda_graphs=not args.no_cuda_graphs,
                compile_mode=args.compile_mode,
                use_fast_codebook=args.use_fast_codebook,
                compile_codebook_predictor=not args.no_compile_codebook_predictor,
                compile_talker=not args.no_compile_talker,
                matmul_precision=args.matmul_precision,
                profile_prefill=args.profile_prefill,
                profile_nvtx=args.profile_nvtx,
                collect_generation_trace=args.collect_generation_trace,
                prefill_backend=args.prefill_backend,
                prefill_compile_compat_mode=args.prefill_compile_compat_mode,
                prefill_compile_lengths=args.prefill_compile_lengths,
                prefill_compile_on_miss=args.prefill_compile_on_miss,
                prefill_unknown_shape_policy=args.prefill_unknown_shape_policy,
                prefill_compile_policy=args.prefill_compile_policy,
                prefill_allowlist_warmup_manifest=(
                    args.prefill_allowlist_warmup_manifest
                ),
                prefill_allowlist_warmup_repeats=(
                    args.prefill_allowlist_warmup_repeats
                ),
                prefill_allowlist_max_entries=args.prefill_allowlist_max_entries,
                prefill_allowlist_max_abs_threshold=(
                    args.prefill_allowlist_max_abs_threshold
                ),
                prefill_require_precompiled=args.prefill_require_precompiled,
                prefill_first_chunk_warmup_enabled=(
                    args.prefill_first_chunk_warmup
                ),
                prefill_first_chunk_warmup_length=(
                    args.prefill_first_chunk_warmup_length
                ),
                prefill_generation_prime_enabled=args.prefill_generation_prime,
                allow_request_sampling_overrides=(
                    args.allow_request_sampling_overrides
                ),
                do_sample=not args.no_sample,
                temperature=args.temperature,
                top_k=args.top_k,
                top_p=args.top_p,
                repetition_penalty=args.repetition_penalty,
                seed=args.seed,
                seed_mode=args.seed_mode,
                warmup_seed=args.warmup_seed,
                warmup_synthesis_enabled=args.warmup_synthesis,
                warmup_synthesis_passes=args.warmup_synthesis_passes,
                warmup_unbounded_passes=args.warmup_unbounded_passes,
                warmup_max_output_chunks=args.warmup_max_output_chunks,
                warmup_text=args.warmup_text,
                warmup_language=args.warmup_language,
                warmup_speaker=args.warmup_speaker,
                warmup_instruction=args.warmup_instruction,
            )
        raise ValueError(f"unsupported engine command: {engine_command}")

    engine_name = args.engine
    if args.mock:
        if engine_name is not None and engine_name != "mock":
            raise ValueError("--mock cannot be combined with --engine qwen")
        engine_name = "mock"
    if engine_name is None:
        raise ValueError(
            "choose an engine subcommand or use --mock/--engine mock"
        )

    if engine_name == "mock":
        return MockEngineConfig(
            chunk_count=_value_or_default(args.legacy_mock_chunks, 3),
            chunk_duration_ms=_value_or_default(args.legacy_mock_chunk_ms, 100),
            chunk_delay_seconds=_value_or_default(args.legacy_mock_chunk_delay, 0.0),
        )
    if engine_name == "qwen":
        return QwenEngineConfig(
            model_path=_value_or_default(args.legacy_model_path, ""),
            device=_value_or_default(args.legacy_device, "cuda"),
            dtype=_value_or_default(args.legacy_dtype, "auto"),
            attn_implementation=_value_or_default(
                args.legacy_attn_implementation,
                "",
            ),
        )
    raise ValueError(f"unsupported engine: {engine_name}")


def _add_root_server_options(parser: argparse.ArgumentParser) -> None:
    server_group = parser.add_argument_group("server options")
    server_group.add_argument("--worker-version", dest="root_worker_version")
    server_group.add_argument(
        "--output-queue-size",
        dest="root_output_queue_size",
        type=int,
    )
    server_group.add_argument(
        "--canary-runtime-profile-manifest",
        dest="root_canary_runtime_profile_manifest",
        type=Path,
    )
    server_group.add_argument(
        "--canary-compiled-allowlist-manifest",
        dest="root_canary_compiled_allowlist_manifest",
        type=Path,
    )


def _server_options_parent_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker-version", dest="command_worker_version")
    parser.add_argument(
        "--output-queue-size",
        dest="command_output_queue_size",
        type=int,
    )
    parser.add_argument(
        "--canary-runtime-profile-manifest",
        dest="command_canary_runtime_profile_manifest",
        type=Path,
    )
    parser.add_argument(
        "--canary-compiled-allowlist-manifest",
        dest="command_canary_compiled_allowlist_manifest",
        type=Path,
    )
    return parser


def _add_legacy_engine_options(parser: argparse.ArgumentParser) -> None:
    engine_group = parser.add_argument_group("legacy engine selection")
    engine_group.add_argument(
        "--mock",
        action="store_true",
        help="Shortcut for --engine mock.",
    )
    engine_group.add_argument(
        "--engine",
        choices=("mock", "qwen"),
        default=None,
        help="Engine backend to run. Only mock is implemented at this stage.",
    )

    mock_group = parser.add_argument_group("legacy mock engine options")
    mock_group.add_argument("--mock-chunks", dest="legacy_mock_chunks", type=int)
    mock_group.add_argument("--mock-chunk-ms", dest="legacy_mock_chunk_ms", type=int)
    mock_group.add_argument(
        "--mock-chunk-delay",
        dest="legacy_mock_chunk_delay",
        type=float,
    )

    qwen_group = parser.add_argument_group("legacy future qwen engine options")
    qwen_group.add_argument("--model-path", dest="legacy_model_path")
    qwen_group.add_argument("--device", dest="legacy_device")
    qwen_group.add_argument("--dtype", dest="legacy_dtype")
    qwen_group.add_argument(
        "--attn-implementation",
        dest="legacy_attn_implementation",
    )


def _add_mock_subcommand(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    server_options: argparse.ArgumentParser,
) -> None:
    mock_parser = subparsers.add_parser(
        "mock",
        parents=[server_options],
        help="Run the deterministic mock engine.",
    )
    mock_parser.add_argument(
        "--chunks",
        "--mock-chunks",
        dest="mock_chunks",
        type=int,
        default=3,
    )
    mock_parser.add_argument(
        "--chunk-ms",
        "--mock-chunk-ms",
        dest="mock_chunk_ms",
        type=int,
        default=100,
    )
    mock_parser.add_argument(
        "--chunk-delay",
        "--mock-chunk-delay",
        dest="mock_chunk_delay",
        type=float,
        default=0.0,
    )


def _add_qwen_subcommand(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    server_options: argparse.ArgumentParser,
) -> None:
    qwen_parser = subparsers.add_parser(
        "qwen",
        parents=[server_options],
        help="Run the Qwen3-TTS engine.",
    )
    qwen_parser.add_argument("--model-path", required=True)
    qwen_parser.add_argument(
        "--runtime-backend",
        choices=("upstream", "faster"),
        default="upstream",
        help="Select the Qwen inference implementation.",
    )
    qwen_parser.add_argument("--device", default="cuda")
    qwen_parser.add_argument("--dtype", default="auto")
    qwen_parser.add_argument("--attn-implementation", default="")
    qwen_parser.add_argument("--max-seq-len", type=int, default=2048)
    qwen_parser.add_argument(
        "--max-audio-seconds-per-utterance",
        type=float,
        default=None,
        help=(
            "Fail a request after this much generated PCM audio instead of "
            "reporting a normal completion; omit for diagnostic runs."
        ),
    )
    qwen_parser.add_argument("--emit-every-frames", type=int, default=8)
    qwen_parser.add_argument(
        "--emit-chunk-schedule",
        type=_parse_emit_chunk_schedule,
        default=(),
        help=(
            "Optional Faster-only first/second/steady PCM frame schedule; "
            "its last value is reused for steady state."
        ),
    )
    qwen_parser.add_argument(
        "--compiled-emit-chunk-schedule",
        type=_parse_emit_chunk_schedule,
        default=(),
        help=(
            "Optional Faster-only schedule selected after a compiled allowlist "
            "prefill."
        ),
    )
    qwen_parser.add_argument(
        "--eager-emit-chunk-schedule",
        type=_parse_emit_chunk_schedule,
        default=(),
        help="Optional Faster-only schedule selected after an eager unknown prefill.",
    )
    qwen_parser.add_argument("--decode-window-frames", type=int, default=80)
    qwen_parser.add_argument("--overlap-samples", type=int, default=0)
    qwen_parser.add_argument(
        "--enable-streaming-optimizations",
        action="store_true",
        help="Call the Qwen fork's torch.compile/CUDA graph optimization hook.",
    )
    qwen_parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Disable torch.compile when streaming optimizations are enabled.",
    )
    qwen_parser.add_argument(
        "--no-cuda-graphs",
        action="store_true",
        help="Disable CUDA graph capture when streaming optimizations are enabled.",
    )
    qwen_parser.add_argument("--compile-mode", default="reduce-overhead")
    qwen_parser.add_argument(
        "--use-fast-codebook",
        action="store_true",
        help="Enable the Qwen fork's fast codebook generation path.",
    )
    qwen_parser.add_argument(
        "--no-compile-codebook-predictor",
        action="store_true",
        help="Do not compile the codebook predictor.",
    )
    qwen_parser.add_argument(
        "--no-compile-talker",
        action="store_true",
        help="Do not compile the talker model.",
    )
    qwen_parser.add_argument(
        "--matmul-precision",
        choices=("highest", "high", "medium"),
        default="",
        help="Set torch float32 matmul precision before Qwen model load.",
    )
    qwen_parser.add_argument(
        "--profile-prefill",
        action="store_true",
        help="Emit detailed faster-backend prefill timing in worker metrics.",
    )
    qwen_parser.add_argument(
        "--profile-nvtx",
        action="store_true",
        help="Emit faster-backend NVTX ranges for external profilers.",
    )
    qwen_parser.add_argument(
        "--collect-generation-trace",
        action="store_true",
        help="Emit complete faster-backend generation trace in worker metrics.",
    )
    qwen_parser.add_argument(
        "--prefill-backend",
        choices=(
            "eager",
            "compile_backend_eager",
            "compile_backend_aot_eager",
            "compile_default",
            "compile_inductor_default",
            "compile_reduce_overhead",
        ),
        default="eager",
        help="Select the faster-backend talker prefill implementation.",
    )
    qwen_parser.add_argument(
        "--prefill-compile-compat-mode",
        choices=("none", "strict_bf16_sdpa_v1"),
        default="none",
        help="Select the faster-backend compiled prefill compatibility mode.",
    )
    qwen_parser.add_argument(
        "--prefill-compile-lengths",
        type=_parse_prefill_compile_lengths,
        default=(),
        help="Comma-separated exact talker prefill lengths that may use "
        "compiled prefill.",
    )
    qwen_parser.add_argument(
        "--no-prefill-compile-on-miss",
        action="store_false",
        dest="prefill_compile_on_miss",
        default=True,
        help="Use eager prefill for lengths outside --prefill-compile-lengths.",
    )
    qwen_parser.add_argument(
        "--prefill-unknown-shape-policy",
        choices=("eager", "error"),
        default="eager",
        help="Choose eager fallback or fail-fast for unknown compiled prefill shapes.",
    )
    qwen_parser.add_argument(
        "--prefill-compile-policy",
        choices=("diagnostic_dynamic", "exact_allowlist"),
        default="diagnostic_dynamic",
        help="Select diagnostic dynamic compile or product exact allowlist mode.",
    )
    qwen_parser.add_argument(
        "--prefill-allowlist-warmup-manifest",
        default="",
        help="JSON or JSONL prompt manifest used to prewarm exact allowlist shapes.",
    )
    qwen_parser.add_argument(
        "--prefill-allowlist-warmup-repeats",
        type=int,
        default=3,
        help="Compiled prefill repeats per allowlisted shape before ready.",
    )
    qwen_parser.add_argument(
        "--prefill-allowlist-max-entries",
        type=int,
        default=6,
        help="Maximum exact prefill shapes allowed in product mode.",
    )
    qwen_parser.add_argument(
        "--prefill-allowlist-max-abs-threshold",
        type=float,
        default=0.0,
        help="Maximum eager-vs-compiled prefill drift accepted during startup.",
    )
    qwen_parser.add_argument(
        "--prefill-require-precompiled",
        action="store_true",
        help="Reject compiled allowlist cache misses after startup prewarm.",
    )
    qwen_parser.add_argument(
        "--prefill-first-chunk-warmup",
        action="store_true",
        help="Prewarm one representative audio chunk before reporting ready.",
    )
    qwen_parser.add_argument(
        "--prefill-first-chunk-warmup-length",
        type=int,
        default=None,
        help="Exact allowlisted length used by first-chunk startup warmup.",
    )
    qwen_parser.add_argument(
        "--prefill-generation-prime",
        action="store_true",
        help="Run one internal full-EOS generation prime before reporting ready.",
    )
    qwen_parser.add_argument(
        "--allow-request-sampling-overrides",
        action="store_true",
        help=(
            "Allow per-request sampling overrides for an isolated experimental "
            "profile."
        ),
    )
    qwen_parser.add_argument(
        "--no-sample",
        action="store_true",
        help="Use greedy decoding instead of sampling.",
    )
    qwen_parser.add_argument(
        "--temperature",
        type=float,
        default=0.9,
        help="Default sampling temperature for faster Qwen inference.",
    )
    qwen_parser.add_argument(
        "--top-k",
        type=int,
        default=50,
        help="Default top-k candidate limit for faster Qwen inference.",
    )
    qwen_parser.add_argument(
        "--top-p",
        type=float,
        default=1.0,
        help="Default nucleus-sampling probability for faster Qwen inference.",
    )
    qwen_parser.add_argument(
        "--repetition-penalty",
        type=float,
        default=1.05,
        help="Default repetition penalty for faster Qwen inference.",
    )
    qwen_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed Python, NumPy, and torch RNGs for benchmark reproducibility.",
    )
    qwen_parser.add_argument(
        "--seed-mode",
        choices=("request_id", "fixed"),
        default="request_id",
        help="Select how per-request RNG seeds are derived from --seed.",
    )
    qwen_parser.add_argument(
        "--warmup-seed",
        type=int,
        default=None,
        help="Override the RNG seed used for synthesis warmup requests.",
    )
    qwen_parser.add_argument(
        "--warmup-synthesis",
        action="store_true",
        help="Run one synthetic synthesis request before reporting ready.",
    )
    qwen_parser.add_argument(
        "--warmup-synthesis-passes",
        type=int,
        default=1,
        help="Number of warmup synthesis passes to run before reporting ready.",
    )
    qwen_parser.add_argument(
        "--warmup-max-output-chunks",
        type=int,
        default=None,
        help="Stop each warmup synthesis pass after this many non-empty PCM chunks.",
    )
    qwen_parser.add_argument(
        "--warmup-unbounded-passes",
        type=int,
        default=0,
        help="Leave this many initial warmup passes unbounded before applying "
        "--warmup-max-output-chunks.",
    )
    qwen_parser.add_argument("--warmup-text", default="Warmup.")
    qwen_parser.add_argument("--warmup-language", default="auto")
    qwen_parser.add_argument("--warmup-speaker", default="")
    qwen_parser.add_argument("--warmup-instruction", default="")
    qwen_parser.add_argument(
        "--engine-startup-mode",
        choices=("auto", "main", "engine_warmup", "engine_load_warmup"),
        default="auto",
        help="Select which thread runs Qwen load and synthesis warmup.",
    )


def _reject_mixed_legacy_engine_flags(args: argparse.Namespace) -> None:
    legacy_values = (
        args.mock,
        args.engine is not None,
        args.legacy_mock_chunks is not None,
        args.legacy_mock_chunk_ms is not None,
        args.legacy_mock_chunk_delay is not None,
        args.legacy_model_path is not None,
        args.legacy_device is not None,
        args.legacy_dtype is not None,
        args.legacy_attn_implementation is not None,
    )
    if any(legacy_values):
        raise ValueError(
            "legacy engine flags cannot be combined with engine subcommands"
        )


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


def _parse_emit_chunk_schedule(value: str) -> tuple[int, ...]:
    text = value.strip()
    if not text:
        return ()
    frames: list[int] = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            raise argparse.ArgumentTypeError(
                "--emit-chunk-schedule must not contain empty items"
            )
        try:
            frame_count = int(item)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "--emit-chunk-schedule must contain integers"
            ) from exc
        if frame_count <= 0:
            raise argparse.ArgumentTypeError(
                "--emit-chunk-schedule must contain positive integers"
            )
        frames.append(frame_count)
    return tuple(frames)


def _selected_worker_version(args: argparse.Namespace) -> str:
    return _selected_server_option(
        args.root_worker_version,
        getattr(args, "command_worker_version", None),
        "worker-version",
        "0.2.0",
    )


def _selected_output_queue_size(args: argparse.Namespace) -> int:
    return _selected_server_option(
        args.root_output_queue_size,
        getattr(args, "command_output_queue_size", None),
        "output-queue-size",
        128,
    )


def _selected_engine_startup_mode(
    args: argparse.Namespace,
    engine: EngineConfig,
) -> Literal["main", "engine_warmup", "engine_load_warmup"]:
    selected = str(getattr(args, "engine_startup_mode", "auto"))
    if selected == "auto":
        if isinstance(engine, QwenEngineConfig):
            return "engine_warmup"
        return "main"
    return cast(
        Literal["main", "engine_warmup", "engine_load_warmup"],
        selected,
    )


def _selected_server_option(
    root_value: T | None,
    command_value: T | None,
    name: str,
    default: T,
) -> T:
    if root_value is not None and command_value is not None:
        raise ValueError(
            f"--{name} cannot be specified both before and after subcommand"
        )
    if command_value is not None:
        return command_value
    if root_value is not None:
        return root_value
    return default


def _value_or_default(value: T | None, default: T) -> T:
    if value is None:
        return default
    return value
