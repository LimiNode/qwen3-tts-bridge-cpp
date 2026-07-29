"""Benchmark first user request latency across fresh worker processes."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from benchmark_packaged_worker import _run_request, _shutdown, _summary
from benchmark_runtime import (
    apply_cpu_affinity,
    gpu_snapshot,
    runtime_fingerprint,
)
from verify_packaged_worker import (
    PackagedWorkerHarness,
    _control_payload,
    _is_control_message,
    _worker_process_args,
)

_PHASE_KEYS = (
    "transport_and_dispatch_residual_ms",
    "client_minus_worker_first_pcm_ready_ms",
    "client_minus_worker_frame_enqueued_ms",
    "client_minus_worker_frame_flushed_estimated_ms",
    "first_frame_output_writer_ms",
    "first_chunk_prefill_ms",
    "first_chunk_ar_decode_ms",
    "first_chunk_ar_ms_per_step",
    "first_chunk_codec_wrapper_residual_ms",
    "first_chunk_pcm_convert_ms",
    "first_chunk_next_wall_ms",
    "first_chunk_text_token_count",
    "first_chunk_instruction_token_count",
    "first_chunk_prefill_sequence_length",
    "first_chunk_talker_prefill_length",
    "first_chunk_prefill_shape_length",
    "first_chunk_tokenize_wall_ms",
    "first_chunk_build_talker_inputs_wall_ms",
    "first_chunk_prefill_total_gpu_ms",
    "first_chunk_prefill_total_stream_elapsed_ms",
    "first_chunk_talker_forward_launch_wall_ms",
    "first_chunk_talker_forward_gpu_ms",
    "first_chunk_talker_forward_stream_elapsed_ms",
    "first_chunk_first_sample_launch_wall_ms",
    "first_chunk_first_sample_gpu_ms",
    "first_chunk_first_sample_stream_elapsed_ms",
    "first_chunk_prefill_kv_launch_wall_ms",
    "first_chunk_prefill_kv_gpu_ms",
    "first_chunk_prefill_kv_stream_elapsed_ms",
    "first_chunk_generation_state_wall_ms",
    "first_chunk_generation_state_gpu_ms",
    "first_chunk_generation_state_stream_elapsed_ms",
    "first_chunk_prefill_to_sync_gpu_ms",
    "first_chunk_prefill_to_sync_stream_elapsed_ms",
    "first_chunk_prefill_sync_wait_ms",
    "first_chunk_prefill_gpu_component_sum_ms",
    "first_chunk_prefill_gpu_partition_error_ms",
    "first_chunk_prefill_gpu_accounting_error_ms",
    "first_chunk_codec_context_assembly_ms",
    "first_chunk_speech_tokenizer_decode_wall_ms",
    "first_chunk_speech_tokenizer_decode_gpu_ms",
    "first_chunk_d2h_ms",
    "first_chunk_numpy_ms",
    "first_chunk_audio_flatten_ms",
    "first_chunk_audio_slice_ms",
    "first_chunk_codec_wrapper_wall_ms",
    "first_chunk_codec_wrapper_other_ms",
    "first_chunk_first_sample_setup_gpu_ms",
    "first_chunk_first_sample_logits_prepare_gpu_ms",
    "first_chunk_first_sample_clone_suppress_gpu_ms",
    "first_chunk_first_sample_temperature_gpu_ms",
    "first_chunk_first_sample_top_k_gpu_ms",
    "first_chunk_first_sample_top_p_gpu_ms",
    "first_chunk_first_sample_softmax_gpu_ms",
    "first_chunk_first_sample_multinomial_gpu_ms",
    "first_chunk_first_sample_argmax_gpu_ms",
    "first_chunk_ar_predictor_graph_gpu_ms",
    "first_chunk_ar_history_update_gpu_ms",
    "first_chunk_ar_codebook_embed_gather_gpu_ms",
    "first_chunk_ar_talker_graph_replay_gpu_ms",
    "first_chunk_ar_logits_prepare_gpu_ms",
    "first_chunk_ar_sample_clone_suppress_gpu_ms",
    "first_chunk_ar_sample_temperature_gpu_ms",
    "first_chunk_ar_sample_top_k_gpu_ms",
    "first_chunk_ar_sample_top_p_gpu_ms",
    "first_chunk_ar_sample_softmax_gpu_ms",
    "first_chunk_ar_sample_multinomial_gpu_ms",
    "first_chunk_ar_sample_argmax_gpu_ms",
    "first_chunk_ar_state_update_gpu_ms",
)


def main() -> int:
    """Run a restart-based packaged worker benchmark."""

    parser = _build_parser()
    args = parser.parse_args()

    worker_executable = args.worker_executable.resolve()
    if not worker_executable.is_file():
        parser.error(f"worker executable was not found: {worker_executable}")
    if args.engine == "qwen" and not args.model_path:
        parser.error("--model-path is required for --engine qwen")
    if args.runs <= 0:
        parser.error("--runs must be greater than zero")
    if args.requests_per_run <= 0:
        parser.error("--requests-per-run must be greater than zero")
    run_shapes = _load_run_shapes(args.run_shapes_jsonl)
    if run_shapes and len(run_shapes) < args.runs:
        parser.error("--run-shapes-jsonl must contain at least --runs rows")

    results = []
    run_summaries = []
    runtime = runtime_fingerprint(
        worker_executable=worker_executable,
        worker_prefix_args=args.worker_prefix_arg,
        args=args,
    )
    _validate_runtime_provenance(args, runtime)
    started_at = time.perf_counter()
    for index in range(args.runs):
        run_shape = _run_shape_for_index(args, run_shapes, index + 1)
        harness = PackagedWorkerHarness(
            worker_executable=worker_executable,
            args=_worker_process_args_for_run(args, index + 1, run_shape),
            timeout_seconds=args.timeout_seconds,
        )
        try:
            affinity_result = apply_cpu_affinity(
                harness.pid,
                _parse_cpu_list(args.cpu_affinity),
            )
            process_started_gpu = gpu_snapshot()
            ready = _hello(harness)
            after_ready_gpu = gpu_snapshot()
            run_requests = []
            for request_index in range(args.requests_per_run):
                gpu_poller = _RequestGpuPoller(args.request_gpu_poll_interval_ms)
                gpu_poller.start()
                try:
                    request_result = _run_request(
                        harness,
                        request_id=request_index + 1,
                        text=str(run_shape["text"]),
                        language=str(run_shape["language"]),
                        speaker=str(run_shape["speaker"]),
                        instruction=str(run_shape["instruction"]),
                    )
                finally:
                    request_gpu_poll = gpu_poller.stop()
                request_result["run_index"] = index + 1
                request_result["request_index"] = request_index + 1
                request_result["shape_label"] = run_shape["label"]
                request_result["text_characters"] = run_shape["text_characters"]
                request_result["ready_warmed_up"] = ready.get("warmed_up")
                request_result["startup_ms"] = ready.get("startup_ms")
                if request_gpu_poll is not None:
                    request_result["gpu_poll"] = request_gpu_poll
                run_requests.append(request_result)
                results.append(request_result)
            _shutdown(harness)
            after_requests_gpu = gpu_snapshot()
            run_summary = _run_summary(
                run_index=index + 1,
                run_shape=run_shape,
                ready=ready,
                requests=run_requests,
                worker_metrics=_worker_metrics(harness.stderr_text()),
                affinity=affinity_result,
                process_started_gpu=process_started_gpu,
                after_ready_gpu=after_ready_gpu,
                after_requests_gpu=after_requests_gpu,
            )
            run_summaries.append(run_summary)
            if args.partial_output:
                _write_json_file(
                    args.partial_output,
                    _build_report(args, runtime, results, run_summaries),
                )
            if args.progress_every_runs and (index + 1) % args.progress_every_runs == 0:
                progress_line = _progress_line(
                    done=index + 1,
                    total=args.runs,
                    started_at=started_at,
                    run_summary=run_summary,
                )
                if args.progress_output:
                    _append_line(args.progress_output, progress_line)
                else:
                    print(progress_line, file=sys.stderr, flush=True)
        finally:
            harness.close()

    print(
        json.dumps(
            _build_report(args, runtime, results, run_summaries),
            sort_keys=True,
        )
    )
    return 0


def _build_report(
    args: argparse.Namespace,
    runtime: dict[str, object],
    results: list[dict[str, object]],
    run_summaries: list[dict[str, object]],
) -> dict[str, object]:
    first_requests = [
        cast(dict[str, object], run["first_request"])
        for run in run_summaries
        if isinstance(run.get("first_request"), dict)
    ]
    steady_requests = [
        cast(dict[str, object], run["steady_request_median"])
        for run in run_summaries
        if isinstance(run.get("steady_request_median"), dict)
    ]
    pipeline_requests = [
        request
        for run in run_summaries
        for request in cast(list[dict[str, object]], run["requests"])
    ]
    paired_deltas = [
        {"paired_delta_first_audio_ms": run["paired_delta_first_audio_ms"]}
        for run in run_summaries
        if isinstance(run.get("paired_delta_first_audio_ms"), (int, float))
    ]
    paired_phase_deltas = [
        cast(dict[str, object], run["paired_phase_delta"])
        for run in run_summaries
        if isinstance(run.get("paired_phase_delta"), dict)
    ]

    return {
        "config": {
            "runs": args.runs,
            "text": args.text,
            "language": args.language,
            "speaker": args.speaker,
            "instruction": args.instruction,
            "warmup_synthesis": args.warmup_synthesis,
            "warmup_synthesis_passes": args.warmup_synthesis_passes,
            "warmup_unbounded_passes": args.warmup_unbounded_passes,
            "warmup_max_output_chunks": args.warmup_max_output_chunks,
            "warmup_text": args.warmup_text,
            "warmup_language": args.warmup_language,
            "warmup_speaker": args.warmup_speaker,
            "warmup_instruction": args.warmup_instruction,
            "engine_startup_mode": args.engine_startup_mode,
            "seed": args.seed,
            "seed_mode": args.seed_mode,
            "warmup_seed": args.warmup_seed,
            "run_seed_step": args.run_seed_step,
            "run_warmup_seed_step": args.run_warmup_seed_step,
            "requests_per_run": args.requests_per_run,
            "cpu_affinity": args.cpu_affinity,
            "profile_prefill": args.profile_prefill,
            "profile_nvtx": args.profile_nvtx,
            "prefill_backend": args.prefill_backend,
            "prefill_compile_compat_mode": args.prefill_compile_compat_mode,
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
            "prefill_allowlist_max_entries": args.prefill_allowlist_max_entries,
            "prefill_allowlist_max_abs_threshold": (
                args.prefill_allowlist_max_abs_threshold
            ),
            "prefill_require_precompiled": args.prefill_require_precompiled,
            "prefill_first_chunk_warmup": args.prefill_first_chunk_warmup,
            "prefill_first_chunk_warmup_length": args.prefill_first_chunk_warmup_length,
            "expected_faster_wheel_sha256": args.expected_faster_wheel_sha256,
            "allow_unverified_faster_wheel": args.allow_unverified_faster_wheel,
            "do_sample": not args.no_sample,
            "request_gpu_poll_interval_ms": args.request_gpu_poll_interval_ms,
            "warmup_from_run_shape": args.warmup_from_run_shape,
            "run_shapes_jsonl": str(args.run_shapes_jsonl)
            if args.run_shapes_jsonl
            else None,
            "outlier_delta_threshold_ms": args.outlier_delta_threshold_ms,
        },
        "runtime": runtime,
        "summary": {
            "all_requests": {
                "first_audio_ms": _summary(results, "first_audio_ms"),
                "completed_ms": _summary(results, "completed_ms"),
                "real_time_factor": _summary(results, "real_time_factor"),
                "inverse_rtf": _summary(results, "inverse_rtf"),
            },
            "first_request": {
                "first_audio_ms": _summary(first_requests, "first_audio_ms"),
                "completed_ms": _summary(first_requests, "completed_ms"),
                "real_time_factor": _summary(first_requests, "real_time_factor"),
                "inverse_rtf": _summary(first_requests, "inverse_rtf"),
            },
            "steady_request_median": {
                "first_audio_ms": _summary(steady_requests, "first_audio_ms"),
                "completed_ms": _summary(steady_requests, "completed_ms"),
                "real_time_factor": _summary(steady_requests, "real_time_factor"),
                "inverse_rtf": _summary(steady_requests, "inverse_rtf"),
            },
            "paired_delta": {
                "first_audio_ms": _summary(
                    paired_deltas,
                    "paired_delta_first_audio_ms",
                ),
            },
            "pipeline": _phase_summary(pipeline_requests),
            "first_request_pipeline": _phase_summary(first_requests),
            "steady_request_median_pipeline": _phase_summary(
                steady_requests,
            ),
            "profile_validation": _profile_validation_summary(pipeline_requests),
            "paired_phase_delta": _phase_summary(paired_phase_deltas),
            "paired_delta_residuals": _paired_delta_residual_summary(run_summaries),
            "paired_steady_residuals": _paired_steady_residual_summary(
                run_summaries,
            ),
            "talker_forward_explained_outliers": (
                _talker_forward_explained_outlier_summary(
                    run_summaries,
                    threshold_ms=args.outlier_delta_threshold_ms,
                )
            ),
            "positive_outlier_talker_forward_attribution": (
                _positive_outlier_talker_forward_attribution(
                    run_summaries,
                    threshold_ms=args.outlier_delta_threshold_ms,
                )
            ),
            "by_shape": _shape_summary(
                run_summaries,
                threshold_ms=args.outlier_delta_threshold_ms,
            ),
            "correlations": _correlations(run_summaries),
            "outliers": _outlier_records(
                run_summaries,
                threshold_ms=args.outlier_delta_threshold_ms,
            ),
        },
        "runs": run_summaries,
        "requests": results,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("worker_executable", type=Path)
    parser.add_argument("--worker-prefix-arg", action="append", default=[])
    parser.add_argument("--engine", choices=("mock", "qwen"), default="mock")
    parser.add_argument("--model-path")
    parser.add_argument(
        "--runtime-backend",
        choices=("upstream", "faster"),
        default="upstream",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--attn-implementation", default="")
    parser.add_argument("--max-seq-len", type=int, default=2048)
    parser.add_argument("--emit-every-frames", type=int, default=8)
    parser.add_argument("--decode-window-frames", type=int, default=80)
    parser.add_argument("--overlap-samples", type=int, default=0)
    parser.add_argument("--enable-streaming-optimizations", action="store_true")
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument("--no-cuda-graphs", action="store_true")
    parser.add_argument("--compile-mode", default="reduce-overhead")
    parser.add_argument("--use-fast-codebook", action="store_true")
    parser.add_argument("--no-compile-codebook-predictor", action="store_true")
    parser.add_argument("--no-compile-talker", action="store_true")
    parser.add_argument("--matmul-precision", default="")
    parser.add_argument("--profile-prefill", action="store_true")
    parser.add_argument("--profile-nvtx", action="store_true")
    parser.add_argument(
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
    )
    parser.add_argument(
        "--prefill-compile-compat-mode",
        choices=("none", "strict_bf16_sdpa_v1"),
        default="none",
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
    parser.add_argument(
        "--expected-faster-wheel-sha256",
        default="",
        help=(
            "Require faster_qwen3_tts installed_archive_sha256 to match this "
            "condition-specific wheel hash."
        ),
    )
    parser.add_argument(
        "--allow-unverified-faster-wheel",
        action="store_true",
        help=(
            "Allow faster backend runs when the installed wheel does not match "
            "the single retained wheel. Use only for controlled A/B/C wheel "
            "experiments that record wheel provenance separately."
        ),
    )
    parser.add_argument("--no-sample", action="store_true")
    parser.add_argument(
        "--request-gpu-poll-interval-ms",
        type=float,
        default=0.0,
        help="Poll nvidia-smi during each request when greater than zero.",
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--seed-mode",
        choices=("request_id", "fixed"),
        default="request_id",
    )
    parser.add_argument("--warmup-seed", type=int, default=None)
    parser.add_argument(
        "--run-seed-step",
        type=int,
        default=0,
        help="Add this offset per fresh-worker run when --seed is set.",
    )
    parser.add_argument(
        "--run-warmup-seed-step",
        type=int,
        default=0,
        help="Add this offset per fresh-worker run when --warmup-seed is set.",
    )
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-synthesis-passes", type=int, default=1)
    parser.add_argument("--warmup-unbounded-passes", type=int, default=0)
    parser.add_argument("--warmup-max-output-chunks", type=int, default=None)
    parser.add_argument("--warmup-text", default="Warmup.")
    parser.add_argument("--warmup-language", default="auto")
    parser.add_argument("--warmup-speaker", default="")
    parser.add_argument("--warmup-instruction", default="")
    parser.add_argument(
        "--warmup-from-run-shape",
        action="store_true",
        help="Use each run shape as that fresh worker's synthesis warmup prompt.",
    )
    parser.add_argument(
        "--engine-startup-mode",
        choices=("auto", "main", "engine_warmup", "engine_load_warmup"),
        default="auto",
    )
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--mock-chunks", type=int, default=1)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--requests-per-run", type=int, default=1)
    parser.add_argument(
        "--partial-output",
        type=Path,
        default=None,
        help="Optional JSON file updated after each completed fresh-worker run.",
    )
    parser.add_argument(
        "--progress-every-runs",
        type=int,
        default=0,
        help="Write a compact progress line to stderr every N completed runs.",
    )
    parser.add_argument(
        "--progress-output",
        type=Path,
        default=None,
        help="Optional file for progress lines; avoids PowerShell stderr wrapping.",
    )
    parser.add_argument(
        "--cpu-affinity",
        default="",
        help="Comma-separated CPU indices to apply to each worker process.",
    )
    parser.add_argument("--text", default="Packaged worker restart benchmark request.")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--instruction", default="")
    parser.add_argument(
        "--run-shapes-jsonl",
        type=Path,
        default=None,
        help="Optional JSONL schedule with per-run label/text/language/speaker.",
    )
    parser.add_argument(
        "--outlier-delta-threshold-ms",
        type=float,
        default=20.0,
        help="Paired first-audio delta threshold for outlier records.",
    )
    return parser


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


def _validate_runtime_provenance(
    args: argparse.Namespace,
    runtime: dict[str, object],
) -> None:
    if args.engine != "qwen" or args.runtime_backend != "faster":
        return
    imports = runtime.get("imports")
    if not isinstance(imports, dict):
        raise RuntimeError("runtime provenance is missing imports")
    faster = imports.get("faster_qwen3_tts")
    if not isinstance(faster, dict):
        raise RuntimeError("runtime provenance is missing faster_qwen3_tts")
    distribution = faster.get("distribution")
    if not isinstance(distribution, dict):
        raise RuntimeError("faster_qwen3_tts distribution provenance is missing")
    expected_sha = str(getattr(args, "expected_faster_wheel_sha256", "")).strip()
    if expected_sha:
        installed_sha = distribution.get("installed_archive_sha256")
        if not isinstance(installed_sha, str):
            raise RuntimeError(
                "faster_qwen3_tts installed archive SHA256 is missing"
            )
        if installed_sha.lower() != expected_sha.lower():
            raise RuntimeError(
                "faster_qwen3_tts installed archive SHA256 mismatch: "
                f"expected {expected_sha}, got {installed_sha}"
            )
        return
    if getattr(args, "allow_unverified_faster_wheel", False):
        return
    if distribution.get("retained_wheel_match_verified") is not True:
        raise RuntimeError(
            "faster_qwen3_tts retained wheel provenance was not verified"
        )


class _RequestGpuPoller:
    def __init__(
        self,
        interval_ms: float,
        *,
        snapshot_fn: Callable[[], dict[str, object]] = gpu_snapshot,
    ) -> None:
        self._interval_seconds = max(float(interval_ms), 0.0) / 1000.0
        self._snapshot_fn = snapshot_fn
        self._stop = threading.Event()
        self._samples: list[dict[str, object]] = []
        self._thread: threading.Thread | None = None
        self._started_at = 0.0

    def start(self) -> None:
        if self._interval_seconds <= 0.0:
            return
        self._started_at = time.perf_counter()
        self._thread = threading.Thread(
            target=self._run,
            name="benchmark-gpu-poller",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> dict[str, object] | None:
        if self._thread is None:
            return None
        self._stop.set()
        self._thread.join(timeout=max(self._interval_seconds * 2.0, 1.0))
        samples = list(self._samples)
        return {
            "interval_ms": self._interval_seconds * 1000.0,
            "sample_count": len(samples),
            "samples": samples,
            "summary": _gpu_poll_summary(samples),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            snapshot = self._snapshot_fn()
            self._samples.append(
                {
                    "t_ms": (time.perf_counter() - self._started_at) * 1000.0,
                    "snapshot": snapshot,
                }
            )
            self._stop.wait(self._interval_seconds)


def _worker_process_args_for_run(
    args: argparse.Namespace,
    run_index: int,
    run_shape: dict[str, object] | None = None,
) -> list[str]:
    needs_run_args = (
        (args.seed is not None and args.run_seed_step != 0)
        or (args.warmup_seed is not None and args.run_warmup_seed_step != 0)
        or (args.warmup_from_run_shape and run_shape is not None)
    )
    if not needs_run_args:
        return _worker_process_args(args)

    run_args = argparse.Namespace(**vars(args))
    if run_args.seed is not None:
        run_args.seed = int(run_args.seed) + (run_index - 1) * int(
            args.run_seed_step
        )
    if run_args.warmup_seed is not None:
        run_args.warmup_seed = int(run_args.warmup_seed) + (run_index - 1) * int(
            args.run_warmup_seed_step
        )
    if args.warmup_from_run_shape and run_shape is not None:
        run_args.warmup_text = str(run_shape["text"])
        run_args.warmup_language = str(run_shape["language"])
        run_args.warmup_speaker = str(run_shape["speaker"])
        run_args.warmup_instruction = str(run_shape["instruction"])
    return _worker_process_args(run_args)


def _write_json_file(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(
        json.dumps(report, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _load_run_shapes(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    shapes = []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            message = f"invalid shape JSONL at line {line_number}: {exc}"
            raise ValueError(message) from exc
        if not isinstance(item, dict):
            raise ValueError(f"shape JSONL line {line_number} must be an object")
        text = item.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError(f"shape JSONL line {line_number} must contain text")
        label = item.get("label", f"shape_{line_number}")
        if not isinstance(label, str) or not label:
            raise ValueError(f"shape JSONL line {line_number} has invalid label")
        shapes.append(
            {
                "label": label,
                "text": text,
                "language": item.get("language", "auto"),
                "speaker": item.get("speaker", ""),
                "instruction": item.get("instruction", ""),
            }
        )
    return shapes


def _run_shape_for_index(
    args: argparse.Namespace,
    run_shapes: list[dict[str, object]],
    run_index: int,
) -> dict[str, object]:
    if run_shapes:
        shape = dict(run_shapes[run_index - 1])
    else:
        shape = {
            "label": "default",
            "text": args.text,
            "language": args.language,
            "speaker": args.speaker,
            "instruction": args.instruction,
        }
    text = str(shape["text"])
    shape["text_characters"] = len(text)
    return shape


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")


def _progress_line(
    *,
    done: int,
    total: int,
    started_at: float,
    run_summary: dict[str, object],
) -> str:
    elapsed_s = time.perf_counter() - started_at
    first = cast(dict[str, object], run_summary.get("first_request", {}))
    steady = run_summary.get("steady_request_median")
    steady_dict = steady if isinstance(steady, dict) else {}
    return (
        "progress "
        f"{done}/{total} "
        f"elapsed_s={elapsed_s:.1f} "
        f"last_first_audio_ms={_format_optional_number(first.get('first_audio_ms'))} "
        "last_steady_first_audio_ms="
        f"{_format_optional_number(steady_dict.get('first_audio_ms'))} "
        "last_delta_first_audio_ms="
        f"{_format_optional_number(run_summary.get('paired_delta_first_audio_ms'))}"
    )


def _format_optional_number(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1f}"
    return "n/a"


def _hello(harness: PackagedWorkerHarness) -> dict[str, object]:
    start = time.perf_counter()
    harness.send_control(
        0,
        {
            "message_type": "hello",
            "client_name": "packaged-worker-restart-benchmark",
            "client_version": "0.2.0",
        },
    )
    ready = _control_payload(
        harness.read_frame(lambda frame: _is_control_message(frame, "ready", 0))
    )
    ready["startup_ms"] = (time.perf_counter() - start) * 1000.0
    return ready


def _run_summary(
    *,
    run_index: int,
    run_shape: dict[str, object],
    ready: dict[str, object],
    requests: list[dict[str, object]],
    worker_metrics: list[dict[str, object]],
    affinity: dict[str, object],
    process_started_gpu: dict[str, object],
    after_ready_gpu: dict[str, object],
    after_requests_gpu: dict[str, object],
) -> dict[str, object]:
    enriched_requests = [
        _with_request_pipeline_metrics(request, worker_metrics)
        for request in requests
    ]
    first_request = enriched_requests[0] if enriched_requests else {}
    steady_requests = enriched_requests[1:]
    steady_median = _median_request(steady_requests)
    paired_delta: float | None = None
    paired_phase_delta = _phase_delta(first_request, steady_median)
    paired_steady_residuals = _paired_steady_residuals(
        first_request,
        steady_requests,
    )
    first_audio = first_request.get("first_audio_ms")
    if isinstance(first_audio, (int, float)) and steady_median is not None:
        steady_first_audio = steady_median.get("first_audio_ms")
        if isinstance(steady_first_audio, (int, float)):
            paired_delta = float(first_audio) - float(steady_first_audio)
    paired_delta_residuals = _paired_delta_residuals(
        paired_delta,
        paired_phase_delta,
    )
    return {
        "run_index": run_index,
        "shape": run_shape,
        "ready": ready,
        "affinity": affinity,
        "gpu": {
            "process_started": process_started_gpu,
            "after_ready": after_ready_gpu,
            "after_requests": after_requests_gpu,
        },
        "warmup_passes": [
            metric
            for metric in worker_metrics
            if metric.get("event") == "engine_warmup_pass"
        ],
        "worker_metrics": worker_metrics,
        "first_request": first_request,
        "steady_requests": steady_requests,
        "steady_request_median": steady_median,
        "paired_delta_first_audio_ms": paired_delta,
        "paired_phase_delta": paired_phase_delta,
        "paired_delta_residuals": paired_delta_residuals,
        "paired_steady_residuals": paired_steady_residuals,
        "requests": enriched_requests,
    }


def _shape_summary(
    run_summaries: list[dict[str, object]],
    *,
    threshold_ms: float = 20.0,
) -> dict[str, object]:
    by_shape: dict[str, list[dict[str, object]]] = {}
    for run in run_summaries:
        shape = run.get("shape")
        if not isinstance(shape, dict):
            continue
        label = shape.get("label")
        if not isinstance(label, str):
            continue
        by_shape.setdefault(label, []).append(run)

    summary: dict[str, object] = {}
    for label, runs in sorted(by_shape.items()):
        first_requests = [
            cast(dict[str, object], run["first_request"])
            for run in runs
            if isinstance(run.get("first_request"), dict)
        ]
        steady_requests = [
            cast(dict[str, object], run["steady_request_median"])
            for run in runs
            if isinstance(run.get("steady_request_median"), dict)
        ]
        paired_deltas = [
            {"paired_delta_first_audio_ms": run["paired_delta_first_audio_ms"]}
            for run in runs
            if isinstance(run.get("paired_delta_first_audio_ms"), (int, float))
        ]
        summary[label] = {
            "runs": len(runs),
            "text_characters": _summary(
                [cast(dict[str, object], run["shape"]) for run in runs],
                "text_characters",
            ),
            "first_request": {
                "first_audio_ms": _summary(first_requests, "first_audio_ms"),
                "first_chunk_text_token_count": _summary(
                    first_requests,
                    "first_chunk_text_token_count",
                ),
                "first_chunk_instruction_token_count": _summary(
                    first_requests,
                    "first_chunk_instruction_token_count",
                ),
                "first_chunk_prefill_sequence_length": _summary(
                    first_requests,
                    "first_chunk_prefill_sequence_length",
                ),
                "first_chunk_talker_prefill_length": _summary(
                    first_requests,
                    "first_chunk_talker_prefill_length",
                ),
            },
            "steady_request_median": {
                "first_audio_ms": _summary(steady_requests, "first_audio_ms"),
            },
            "paired_delta": {
                "first_audio_ms": _summary(
                    paired_deltas,
                    "paired_delta_first_audio_ms",
                ),
            },
            "slow_delta_count": sum(
                1
                for run in runs
                if _is_slow_delta(run, threshold_ms=threshold_ms)
            ),
            "positive_tail_count": sum(
                1
                for run in runs
                if _is_positive_tail(run, threshold_ms=threshold_ms)
            ),
            "negative_tail_count": sum(
                1
                for run in runs
                if _is_negative_tail(run, threshold_ms=threshold_ms)
            ),
            "unstable_count": sum(
                1
                for run in runs
                if _is_unstable_delta(run, threshold_ms=threshold_ms)
            ),
        }
    return summary


def _is_slow_delta(run: dict[str, object], threshold_ms: float = 20.0) -> bool:
    return _is_positive_tail(run, threshold_ms=threshold_ms)


def _is_positive_tail(run: dict[str, object], threshold_ms: float = 20.0) -> bool:
    delta = _number(run.get("paired_delta_first_audio_ms"))
    return delta is not None and delta > threshold_ms


def _is_negative_tail(run: dict[str, object], threshold_ms: float = 20.0) -> bool:
    delta = _number(run.get("paired_delta_first_audio_ms"))
    return delta is not None and delta < -threshold_ms


def _is_unstable_delta(run: dict[str, object], threshold_ms: float = 20.0) -> bool:
    delta = _number(run.get("paired_delta_first_audio_ms"))
    return delta is not None and abs(delta) > threshold_ms


def _outlier_records(
    run_summaries: list[dict[str, object]],
    *,
    threshold_ms: float,
) -> list[dict[str, object]]:
    outliers = []
    for run in run_summaries:
        delta = _number(run.get("paired_delta_first_audio_ms"))
        if delta is None or abs(delta) <= threshold_ms:
            continue
        tail_kind = "positive" if delta > 0 else "negative"
        phase_delta = run.get("paired_phase_delta")
        residuals = run.get("paired_delta_residuals")
        first_request = run.get("first_request")
        steady_request = run.get("steady_request_median")
        outliers.append(
            {
                "run_index": run.get("run_index"),
                "shape": run.get("shape"),
                "tail_kind": tail_kind,
                "paired_delta_first_audio_ms": delta,
                "paired_phase_delta": phase_delta
                if isinstance(phase_delta, dict)
                else {},
                "paired_delta_residuals": residuals
                if isinstance(residuals, dict)
                else {},
                "first_request": first_request
                if isinstance(first_request, dict)
                else {},
                "steady_request_median": steady_request
                if isinstance(steady_request, dict)
                else {},
                "gpu": run.get("gpu") if isinstance(run.get("gpu"), dict) else {},
                "affinity": run.get("affinity")
                if isinstance(run.get("affinity"), dict)
                else {},
            }
        )
    return outliers


def _paired_delta_residuals(
    paired_delta: float | None,
    paired_phase_delta: dict[str, object],
) -> dict[str, object]:
    if paired_delta is None:
        return {}
    residuals: dict[str, object] = {}
    prefill_delta = _number(paired_phase_delta.get("first_chunk_prefill_ms"))
    if prefill_delta is not None:
        residuals["delta_without_prefill_ms"] = paired_delta - prefill_delta
    first_sample_delta = _number(
        paired_phase_delta.get("first_chunk_first_sample_gpu_ms")
    )
    if first_sample_delta is not None:
        residuals["delta_without_first_sample_ms"] = (
            paired_delta - first_sample_delta
        )
    talker_forward_delta = _number(
        paired_phase_delta.get("first_chunk_talker_forward_stream_elapsed_ms")
    )
    if talker_forward_delta is None:
        talker_forward_delta = _number(
            paired_phase_delta.get("first_chunk_talker_forward_gpu_ms")
        )
    if talker_forward_delta is not None:
        signed_residual = paired_delta - talker_forward_delta
        residuals["delta_without_talker_forward_ms"] = signed_residual
        residuals["absolute_delta_without_talker_forward_ms"] = abs(signed_residual)
        positive_total_delta = max(paired_delta, 0.0)
        talker_explained = min(
            max(talker_forward_delta, 0.0),
            positive_total_delta,
        )
        residuals["talker_explained_ms"] = talker_explained
        residuals["positive_unexplained_without_talker_ms"] = (
            positive_total_delta - talker_explained
        )
        residuals["talker_explained_fraction"] = (
            talker_explained / positive_total_delta
            if positive_total_delta > 0.0
            else None
        )
    prefill_kv_delta = _number(paired_phase_delta.get("first_chunk_prefill_kv_gpu_ms"))
    if prefill_kv_delta is not None:
        residuals["delta_without_prefill_kv_ms"] = paired_delta - prefill_kv_delta

    next_wall_delta = _number(paired_phase_delta.get("first_chunk_next_wall_ms"))
    transport_delta = _number(
        paired_phase_delta.get("transport_and_dispatch_residual_ms")
    )
    if next_wall_delta is not None or transport_delta is not None:
        accounted = (next_wall_delta or 0.0) + (transport_delta or 0.0)
        residuals["phase_accounted_delta_ms"] = accounted
        residuals["phase_accounting_error_ms"] = paired_delta - accounted
        residuals["phase_accounting_model"] = (
            "first_chunk_next_wall_delta + transport_dispatch_delta"
        )
    return residuals


def _paired_steady_residuals(
    first_request: dict[str, object],
    steady_requests: list[dict[str, object]],
) -> dict[str, object]:
    rows = [
        residuals
        for request in steady_requests
        if (
            residuals := _paired_steady_residual(
                first_request,
                request,
            )
        )
    ]
    return {
        "count": len(rows),
        "residuals": rows,
        "summary": {
            "total_delta_ms": _summary(rows, "total_delta_ms"),
            "talker_forward_stream_delta_ms": _summary(
                rows,
                "talker_forward_stream_delta_ms",
            ),
            "unexplained_without_talker_ms": _summary(
                rows,
                "unexplained_without_talker_ms",
            ),
            "positive_unexplained_without_talker_ms": _summary(
                rows,
                "positive_unexplained_without_talker_ms",
            ),
            "absolute_unexplained_without_talker_ms": _summary(
                rows,
                "absolute_unexplained_without_talker_ms",
            ),
            "talker_explained_fraction": _summary(
                rows,
                "talker_explained_fraction",
            ),
        },
    }


def _paired_steady_residual(
    first_request: dict[str, object],
    steady_request: dict[str, object],
) -> dict[str, object]:
    total_delta = _metric_delta(first_request, steady_request, "first_audio_ms")
    if total_delta is None:
        return {}
    talker_delta = _metric_delta(
        first_request,
        steady_request,
        "first_chunk_talker_forward_stream_elapsed_ms",
    )
    if talker_delta is None:
        talker_delta = _metric_delta(
            first_request,
            steady_request,
            "first_chunk_talker_forward_gpu_ms",
        )
    result: dict[str, object] = {
        "steady_request_id": steady_request.get("request_id"),
        "total_delta_ms": total_delta,
    }
    if talker_delta is None:
        return result
    unexplained = total_delta - talker_delta
    positive_total_delta = max(total_delta, 0.0)
    talker_explained = min(max(talker_delta, 0.0), positive_total_delta)
    result.update(
        {
            "talker_forward_stream_delta_ms": talker_delta,
            "unexplained_without_talker_ms": unexplained,
            "absolute_unexplained_without_talker_ms": abs(unexplained),
            "talker_explained_ms": talker_explained,
            "positive_unexplained_without_talker_ms": (
                positive_total_delta - talker_explained
            ),
            "talker_explained_fraction": (
                talker_explained / positive_total_delta
                if positive_total_delta > 0.0
                else None
            ),
        }
    )
    return result


def _metric_delta(
    first_request: dict[str, object],
    steady_request: dict[str, object],
    key: str,
) -> float | None:
    first_value = _number(first_request.get(key))
    steady_value = _number(steady_request.get(key))
    if first_value is None or steady_value is None:
        return None
    return first_value - steady_value


def _paired_delta_residual_summary(
    run_summaries: list[dict[str, object]],
) -> dict[str, object]:
    residuals = [
        cast(dict[str, object], run["paired_delta_residuals"])
        for run in run_summaries
        if isinstance(run.get("paired_delta_residuals"), dict)
    ]
    return {
        "delta_without_prefill_ms": _summary(
            residuals,
            "delta_without_prefill_ms",
        ),
        "phase_accounted_delta_ms": _summary(
            residuals,
            "phase_accounted_delta_ms",
        ),
        "delta_without_first_sample_ms": _summary(
            residuals,
            "delta_without_first_sample_ms",
        ),
        "delta_without_talker_forward_ms": _summary(
            residuals,
            "delta_without_talker_forward_ms",
        ),
        "absolute_delta_without_talker_forward_ms": _summary(
            residuals,
            "absolute_delta_without_talker_forward_ms",
        ),
        "positive_unexplained_without_talker_ms": _summary(
            residuals,
            "positive_unexplained_without_talker_ms",
        ),
        "talker_explained_ms": _summary(
            residuals,
            "talker_explained_ms",
        ),
        "talker_explained_fraction": _summary(
            residuals,
            "talker_explained_fraction",
        ),
        "delta_without_prefill_kv_ms": _summary(
            residuals,
            "delta_without_prefill_kv_ms",
        ),
        "phase_accounting_error_ms": _summary(
            residuals,
            "phase_accounting_error_ms",
        ),
    }


def _paired_steady_residual_summary(
    run_summaries: list[dict[str, object]],
) -> dict[str, object]:
    residual_rows = []
    for run in run_summaries:
        paired_steady = run.get("paired_steady_residuals")
        if not isinstance(paired_steady, dict):
            continue
        rows = paired_steady.get("residuals")
        if not isinstance(rows, list):
            continue
        residual_rows.extend(
            row for row in rows if isinstance(row, dict)
        )
    return {
        "count": len(residual_rows),
        "total_delta_ms": _summary(residual_rows, "total_delta_ms"),
        "talker_forward_stream_delta_ms": _summary(
            residual_rows,
            "talker_forward_stream_delta_ms",
        ),
        "unexplained_without_talker_ms": _summary(
            residual_rows,
            "unexplained_without_talker_ms",
        ),
        "positive_unexplained_without_talker_ms": _summary(
            residual_rows,
            "positive_unexplained_without_talker_ms",
        ),
        "absolute_unexplained_without_talker_ms": _summary(
            residual_rows,
            "absolute_unexplained_without_talker_ms",
        ),
        "talker_explained_fraction": _summary(
            residual_rows,
            "talker_explained_fraction",
        ),
    }


def _profile_validation_summary(requests: list[dict[str, object]]) -> dict[str, object]:
    profiled = [
        request
        for request in requests
        if request.get("first_chunk_profile_prefill_enabled") is True
    ]
    profile_count = len(profiled)
    return {
        "all_profile_statuses": _string_counts(
            requests,
            "first_chunk_profile_status",
        ),
        "profiled_first_chunk_count": profile_count,
        "profile_complete_count": _count_true(
            profiled,
            "first_chunk_profile_complete",
        ),
        "events_complete_count": _count_true(
            profiled,
            "first_chunk_events_complete",
        ),
        "components_finite_count": _count_true(
            profiled,
            "first_chunk_components_finite",
        ),
        "components_nonnegative_count": _count_true(
            profiled,
            "first_chunk_components_nonnegative",
        ),
        "all_component_streams_equal_count": _count_true(
            profiled,
            "first_chunk_all_component_streams_equal",
        ),
        "profile_complete_fraction": _fraction_true(
            profiled,
            "first_chunk_profile_complete",
        ),
        "all_component_streams_equal_fraction": _fraction_true(
            profiled,
            "first_chunk_all_component_streams_equal",
        ),
        "profile_paths": _string_counts(profiled, "first_chunk_profile_path"),
        "profile_statuses": _string_counts(profiled, "first_chunk_profile_status"),
        "profile_request_roles": _string_counts(
            profiled,
            "first_chunk_profile_request_role",
        ),
        "prefill_shape_policies": _string_counts(
            requests,
            "first_chunk_prefill_shape_policy",
        ),
        "prefill_shape_allowlist_hit_count": _count_true(
            requests,
            "first_chunk_prefill_shape_allowlist_hit",
        ),
    }


def _count_true(rows: list[dict[str, object]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def _fraction_true(rows: list[dict[str, object]], key: str) -> float | None:
    if not rows:
        return None
    return _count_true(rows, key) / len(rows)


def _string_counts(rows: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key)
        if isinstance(value, str):
            counts[value] = counts.get(value, 0) + 1
    return counts


def _talker_forward_explained_outlier_summary(
    run_summaries: list[dict[str, object]],
    *,
    threshold_ms: float,
) -> dict[str, object]:
    positive_outliers = []
    declassified = []
    for run in run_summaries:
        delta = _number(run.get("paired_delta_first_audio_ms"))
        if delta is None or delta <= threshold_ms:
            continue
        positive_outliers.append(run)
        residuals = run.get("paired_delta_residuals")
        unexplained = (
            _number(residuals.get("positive_unexplained_without_talker_ms"))
            if isinstance(residuals, dict)
            else None
        )
        if unexplained is not None and unexplained <= threshold_ms:
            declassified.append(run)
    count = len(positive_outliers)
    declassified_count = len(declassified)
    return {
        "threshold_ms": threshold_ms,
        "positive_outlier_count": count,
        "declassified_below_threshold_after_talker_forward_count": (
            declassified_count
        ),
        "declassified_below_threshold_after_talker_forward_fraction": (
            declassified_count / count if count else None
        ),
        "legacy_explained_by_talker_forward_count": declassified_count,
        "legacy_explained_by_talker_forward_fraction": (
            declassified_count / count if count else None
        ),
    }


def _positive_outlier_talker_forward_attribution(
    run_summaries: list[dict[str, object]],
    *,
    threshold_ms: float,
) -> dict[str, object]:
    rows = []
    for run in run_summaries:
        total_delta = _number(run.get("paired_delta_first_audio_ms"))
        if total_delta is None or total_delta <= threshold_ms:
            continue
        residuals = run.get("paired_delta_residuals")
        if not isinstance(residuals, dict):
            continue
        talker_delta = _number(residuals.get("talker_explained_ms"))
        unexplained = _number(
            residuals.get("positive_unexplained_without_talker_ms")
        )
        explained_fraction = _number(residuals.get("talker_explained_fraction"))
        rows.append(
            {
                "run_index": run.get("run_index"),
                "total_delta_ms": total_delta,
                "talker_positive_delta_ms": talker_delta,
                "positive_unexplained_without_talker_ms": unexplained,
                "talker_explained_fraction": explained_fraction,
                "declassified_below_threshold": (
                    unexplained is not None and unexplained <= threshold_ms
                ),
            }
        )
    return {
        "threshold_ms": threshold_ms,
        "count": len(rows),
        "declassified_below_threshold_count": _count_true(
            rows,
            "declassified_below_threshold",
        ),
        "total_delta_ms": _summary(rows, "total_delta_ms"),
        "talker_positive_delta_ms": _summary(rows, "talker_positive_delta_ms"),
        "positive_unexplained_without_talker_ms": _summary(
            rows,
            "positive_unexplained_without_talker_ms",
        ),
        "talker_explained_fraction": _summary(
            rows,
            "talker_explained_fraction",
        ),
        "explained_fraction_gte_50_count": _count_at_least(
            rows,
            "talker_explained_fraction",
            0.5,
        ),
        "explained_fraction_gte_80_count": _count_at_least(
            rows,
            "talker_explained_fraction",
            0.8,
        ),
        "runs": rows,
    }


def _count_at_least(
    rows: list[dict[str, object]],
    key: str,
    threshold: float,
) -> int:
    return sum(
        1
        for row in rows
        if (value := _number(row.get(key))) is not None and value >= threshold
    )


def _correlations(run_summaries: list[dict[str, object]]) -> dict[str, object]:
    x_key = "paired_delta_first_audio_ms"
    result: dict[str, object] = {
        "total_delta_vs_prefill_delta": _pearson_for_runs(
            run_summaries,
            x_key,
            "first_chunk_prefill_ms",
        ),
        "total_delta_vs_ar_delta": _pearson_for_runs(
            run_summaries,
            x_key,
            "first_chunk_ar_decode_ms",
        ),
        "total_delta_vs_talker_forward_delta": _pearson_for_runs(
            run_summaries,
            x_key,
            "first_chunk_talker_forward_gpu_ms",
        ),
        "total_delta_vs_codec_residual_delta": _pearson_for_runs(
            run_summaries,
            x_key,
            "first_chunk_codec_wrapper_residual_ms",
        ),
        "total_delta_vs_text_characters": _pearson_for_shape(
            run_summaries,
            x_key,
            "text_characters",
        ),
        "total_delta_vs_text_token_count": _pearson_for_first_request(
            run_summaries,
            x_key,
            "first_chunk_text_token_count",
        ),
        "total_delta_vs_prefill_sequence_length": _pearson_for_first_request(
            run_summaries,
            x_key,
            "first_chunk_prefill_sequence_length",
        ),
        "total_delta_vs_talker_prefill_length": _pearson_for_first_request(
            run_summaries,
            x_key,
            "first_chunk_talker_prefill_length",
        ),
    }
    return result


def _pearson_for_runs(
    runs: list[dict[str, object]],
    x_key: str,
    phase_key: str,
) -> dict[str, object]:
    pairs = []
    for run in runs:
        x = _number(run.get(x_key))
        phase_delta = run.get("paired_phase_delta")
        if isinstance(phase_delta, dict):
            y = _number(phase_delta.get(phase_key))
        else:
            y = None
        if x is not None and y is not None:
            pairs.append((x, y))
    return _pearson_summary(pairs)


def _pearson_for_shape(
    runs: list[dict[str, object]],
    x_key: str,
    shape_key: str,
) -> dict[str, object]:
    pairs = []
    for run in runs:
        x = _number(run.get(x_key))
        shape = run.get("shape")
        y = _number(shape.get(shape_key)) if isinstance(shape, dict) else None
        if x is not None and y is not None:
            pairs.append((x, y))
    return _pearson_summary(pairs)


def _pearson_for_first_request(
    runs: list[dict[str, object]],
    x_key: str,
    request_key: str,
) -> dict[str, object]:
    pairs = []
    for run in runs:
        x = _number(run.get(x_key))
        first_request = run.get("first_request")
        y = (
            _number(first_request.get(request_key))
            if isinstance(first_request, dict)
            else None
        )
        if x is not None and y is not None:
            pairs.append((x, y))
    return _pearson_summary(pairs)


def _pearson_summary(pairs: list[tuple[float, float]]) -> dict[str, object]:
    if len(pairs) < 2:
        return {"count": len(pairs), "pearson_r": None}
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denominator_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denominator_x == 0.0 or denominator_y == 0.0:
        return {"count": len(pairs), "pearson_r": None}
    return {"count": len(pairs), "pearson_r": numerator / denominator_x / denominator_y}


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _gpu_poll_summary(samples: list[dict[str, object]]) -> dict[str, object]:
    keys = (
        "utilization.gpu",
        "power.draw",
        "clocks.sm",
        "clocks.mem",
        "temperature.gpu",
    )
    values: dict[str, list[float]] = {key: [] for key in keys}
    available_count = 0
    for sample in samples:
        snapshot = sample.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("available") is not True:
            continue
        gpus = snapshot.get("gpus")
        if not isinstance(gpus, list) or not gpus:
            continue
        first_gpu = gpus[0]
        if not isinstance(first_gpu, dict):
            continue
        available_count += 1
        for key in keys:
            value = _number_from_text(first_gpu.get(key))
            if value is not None:
                values[key].append(value)

    return {
        "available_sample_count": available_count,
        "max_utilization_gpu": _max_or_none(values["utilization.gpu"]),
        "max_power_draw": _max_or_none(values["power.draw"]),
        "max_clocks_sm": _max_or_none(values["clocks.sm"]),
        "max_clocks_mem": _max_or_none(values["clocks.mem"]),
        "max_temperature_gpu": _max_or_none(values["temperature.gpu"]),
    }


def _number_from_text(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _max_or_none(values: list[float]) -> float | None:
    return max(values) if values else None


def _phase_summary(results: list[dict[str, object]]) -> dict[str, object]:
    return {key: _summary(results, key) for key in _PHASE_KEYS}


def _phase_delta(
    first_request: dict[str, object],
    steady_median: dict[str, object] | None,
) -> dict[str, object]:
    if steady_median is None:
        return {}
    result: dict[str, object] = {}
    for key in _PHASE_KEYS:
        first_value = first_request.get(key)
        steady_value = steady_median.get(key)
        if isinstance(first_value, (int, float)) and isinstance(
            steady_value,
            (int, float),
        ):
            result[key] = float(first_value) - float(steady_value)
    return result


def _with_request_pipeline_metrics(
    request: dict[str, object],
    worker_metrics: list[dict[str, object]],
) -> dict[str, object]:
    request_id = request.get("request_id")
    if not isinstance(request_id, int):
        return dict(request)

    metrics = _metrics_by_event(worker_metrics, request_id)
    enriched = dict(request)
    first_pcm_ready_ms = _metric_number(
        metrics,
        "request_first_pcm_ready",
        "first_pcm_ready_ms",
    )
    first_frame_enqueued_ms = _metric_number(
        metrics,
        "request_first_frame_enqueued",
        "first_frame_enqueue_ms",
    )
    first_frame_output_writer_ms = _metric_number(
        metrics,
        "request_first_frame_flushed",
        "output_writer_ms",
    )
    first_frame_flush_ms = _metric_number(
        metrics,
        "request_first_frame_flushed",
        "flush_ms",
    )
    first_frame_queue_ms = _metric_number(
        metrics,
        "request_first_frame_flushed",
        "output_queue_ms",
    )
    first_chunk_phases = metrics.get("request_first_chunk_engine_phases", {})

    _set_if_number(enriched, "worker_first_pcm_ready_ms", first_pcm_ready_ms)
    _set_if_number(enriched, "worker_first_frame_enqueued_ms", first_frame_enqueued_ms)
    _set_if_number(
        enriched,
        "first_frame_output_writer_ms",
        first_frame_output_writer_ms,
    )
    _set_if_number(enriched, "first_frame_flush_ms", first_frame_flush_ms)
    _set_if_number(enriched, "first_frame_output_queue_ms", first_frame_queue_ms)
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "prefill_ms",
        "first_chunk_prefill_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "ar_decode_ms",
        "first_chunk_ar_decode_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "chunk_steps",
        "first_chunk_steps",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "ar_ms_per_step",
        "first_chunk_ar_ms_per_step",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "codec_wrapper_residual_ms",
        "first_chunk_codec_wrapper_residual_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "pcm_convert_ms",
        "first_chunk_pcm_convert_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "next_wall_ms",
        "first_chunk_next_wall_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "text_token_count",
        "first_chunk_text_token_count",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "instruction_token_count",
        "first_chunk_instruction_token_count",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "prefill_sequence_length",
        "first_chunk_prefill_sequence_length",
    )
    for source_key, target_key in (
        ("talker_prefill_length", "first_chunk_talker_prefill_length"),
        ("prefill_shape_length", "first_chunk_prefill_shape_length"),
        ("tokenize_wall_ms", "first_chunk_tokenize_wall_ms"),
        ("build_talker_inputs_wall_ms", "first_chunk_build_talker_inputs_wall_ms"),
        ("prefill_total_gpu_ms", "first_chunk_prefill_total_gpu_ms"),
        (
            "prefill_total_stream_elapsed_ms",
            "first_chunk_prefill_total_stream_elapsed_ms",
        ),
        (
            "talker_forward_launch_wall_ms",
            "first_chunk_talker_forward_launch_wall_ms",
        ),
        ("talker_forward_gpu_ms", "first_chunk_talker_forward_gpu_ms"),
        (
            "talker_forward_stream_elapsed_ms",
            "first_chunk_talker_forward_stream_elapsed_ms",
        ),
        (
            "first_sample_launch_wall_ms",
            "first_chunk_first_sample_launch_wall_ms",
        ),
        ("first_sample_gpu_ms", "first_chunk_first_sample_gpu_ms"),
        (
            "first_sample_stream_elapsed_ms",
            "first_chunk_first_sample_stream_elapsed_ms",
        ),
        ("prefill_kv_launch_wall_ms", "first_chunk_prefill_kv_launch_wall_ms"),
        ("prefill_kv_gpu_ms", "first_chunk_prefill_kv_gpu_ms"),
        (
            "prefill_kv_stream_elapsed_ms",
            "first_chunk_prefill_kv_stream_elapsed_ms",
        ),
        ("generation_state_wall_ms", "first_chunk_generation_state_wall_ms"),
        ("generation_state_gpu_ms", "first_chunk_generation_state_gpu_ms"),
        (
            "generation_state_stream_elapsed_ms",
            "first_chunk_generation_state_stream_elapsed_ms",
        ),
        ("prefill_to_sync_gpu_ms", "first_chunk_prefill_to_sync_gpu_ms"),
        (
            "prefill_to_sync_stream_elapsed_ms",
            "first_chunk_prefill_to_sync_stream_elapsed_ms",
        ),
        ("prefill_sync_wait_ms", "first_chunk_prefill_sync_wait_ms"),
        (
            "prefill_gpu_component_sum_ms",
            "first_chunk_prefill_gpu_component_sum_ms",
        ),
        (
            "prefill_gpu_partition_error_ms",
            "first_chunk_prefill_gpu_partition_error_ms",
        ),
        (
            "prefill_gpu_accounting_error_ms",
            "first_chunk_prefill_gpu_accounting_error_ms",
        ),
        ("codec_context_assembly_ms", "first_chunk_codec_context_assembly_ms"),
        (
            "speech_tokenizer_decode_wall_ms",
            "first_chunk_speech_tokenizer_decode_wall_ms",
        ),
        (
            "speech_tokenizer_decode_gpu_ms",
            "first_chunk_speech_tokenizer_decode_gpu_ms",
        ),
        ("d2h_ms", "first_chunk_d2h_ms"),
        ("numpy_ms", "first_chunk_numpy_ms"),
        ("audio_flatten_ms", "first_chunk_audio_flatten_ms"),
        ("audio_slice_ms", "first_chunk_audio_slice_ms"),
        ("codec_wrapper_wall_ms", "first_chunk_codec_wrapper_wall_ms"),
        ("codec_wrapper_other_ms", "first_chunk_codec_wrapper_other_ms"),
        (
            "first_sample_setup_gpu_ms",
            "first_chunk_first_sample_setup_gpu_ms",
        ),
        (
            "first_sample_logits_prepare_gpu_ms",
            "first_chunk_first_sample_logits_prepare_gpu_ms",
        ),
        (
            "first_sample_clone_suppress_gpu_ms",
            "first_chunk_first_sample_clone_suppress_gpu_ms",
        ),
        (
            "first_sample_temperature_gpu_ms",
            "first_chunk_first_sample_temperature_gpu_ms",
        ),
        ("first_sample_top_k_gpu_ms", "first_chunk_first_sample_top_k_gpu_ms"),
        ("first_sample_top_p_gpu_ms", "first_chunk_first_sample_top_p_gpu_ms"),
        (
            "first_sample_softmax_gpu_ms",
            "first_chunk_first_sample_softmax_gpu_ms",
        ),
        (
            "first_sample_multinomial_gpu_ms",
            "first_chunk_first_sample_multinomial_gpu_ms",
        ),
        ("first_sample_argmax_gpu_ms", "first_chunk_first_sample_argmax_gpu_ms"),
        ("ar_predictor_graph_gpu_ms", "first_chunk_ar_predictor_graph_gpu_ms"),
        ("ar_history_update_gpu_ms", "first_chunk_ar_history_update_gpu_ms"),
        (
            "ar_codebook_embed_gather_gpu_ms",
            "first_chunk_ar_codebook_embed_gather_gpu_ms",
        ),
        (
            "ar_talker_graph_replay_gpu_ms",
            "first_chunk_ar_talker_graph_replay_gpu_ms",
        ),
        ("ar_logits_prepare_gpu_ms", "first_chunk_ar_logits_prepare_gpu_ms"),
        (
            "ar_sample_clone_suppress_gpu_ms",
            "first_chunk_ar_sample_clone_suppress_gpu_ms",
        ),
        (
            "ar_sample_temperature_gpu_ms",
            "first_chunk_ar_sample_temperature_gpu_ms",
        ),
        ("ar_sample_top_k_gpu_ms", "first_chunk_ar_sample_top_k_gpu_ms"),
        ("ar_sample_top_p_gpu_ms", "first_chunk_ar_sample_top_p_gpu_ms"),
        ("ar_sample_softmax_gpu_ms", "first_chunk_ar_sample_softmax_gpu_ms"),
        (
            "ar_sample_multinomial_gpu_ms",
            "first_chunk_ar_sample_multinomial_gpu_ms",
        ),
        ("ar_sample_argmax_gpu_ms", "first_chunk_ar_sample_argmax_gpu_ms"),
        ("ar_state_update_gpu_ms", "first_chunk_ar_state_update_gpu_ms"),
    ):
        _copy_metric_number(enriched, first_chunk_phases, source_key, target_key)
    for source_key, target_key in (
        ("profile_path", "first_chunk_profile_path"),
        ("profile_status", "first_chunk_profile_status"),
        ("profile_request_role", "first_chunk_profile_request_role"),
        ("prefill_backend_requested", "first_chunk_prefill_backend_requested"),
        ("prefill_backend_used", "first_chunk_prefill_backend_used"),
        ("prefill_compile_error", "first_chunk_prefill_compile_error"),
        (
            "prefill_compile_compat_mode",
            "first_chunk_prefill_compile_compat_mode",
        ),
        ("prefill_shape_policy", "first_chunk_prefill_shape_policy"),
    ):
        _copy_metric_string(enriched, first_chunk_phases, source_key, target_key)
    for source_key, target_key in (
        ("profile_schema_version", "first_chunk_profile_schema_version"),
        ("prefill_total_gpu_stream_id", "first_chunk_prefill_total_gpu_stream_id"),
        ("talker_forward_gpu_stream_id", "first_chunk_talker_forward_gpu_stream_id"),
        ("first_sample_gpu_stream_id", "first_chunk_first_sample_gpu_stream_id"),
        ("prefill_kv_gpu_stream_id", "first_chunk_prefill_kv_gpu_stream_id"),
        (
            "generation_state_gpu_stream_id",
            "first_chunk_generation_state_gpu_stream_id",
        ),
        (
            "prefill_to_sync_gpu_stream_id",
            "first_chunk_prefill_to_sync_gpu_stream_id",
        ),
    ):
        _copy_metric_int(enriched, first_chunk_phases, source_key, target_key)
    for source_key, target_key in (
        ("profile_prefill_enabled", "first_chunk_profile_prefill_enabled"),
        ("profile_complete", "first_chunk_profile_complete"),
        ("events_complete", "first_chunk_events_complete"),
        ("components_finite", "first_chunk_components_finite"),
        ("components_nonnegative", "first_chunk_components_nonnegative"),
        (
            "all_component_streams_equal",
            "first_chunk_all_component_streams_equal",
        ),
        ("prefill_compile_fallback", "first_chunk_prefill_compile_fallback"),
        (
            "prefill_compile_compat_applied",
            "first_chunk_prefill_compile_compat_applied",
        ),
        (
            "prefill_compile_compat_reused",
            "first_chunk_prefill_compile_compat_reused",
        ),
        (
            "prefill_shape_allowlist_hit",
            "first_chunk_prefill_shape_allowlist_hit",
        ),
        ("prefill_compile_on_miss", "first_chunk_prefill_compile_on_miss"),
    ):
        _copy_metric_bool(enriched, first_chunk_phases, source_key, target_key)

    if first_frame_enqueued_ms is not None and first_frame_output_writer_ms is not None:
        enriched["worker_first_frame_flushed_estimated_ms"] = (
            first_frame_enqueued_ms + first_frame_output_writer_ms
        )

    client_first_audio_ms = request.get("first_audio_ms")
    if isinstance(client_first_audio_ms, (int, float)):
        if first_pcm_ready_ms is not None:
            residual_ms = (
                float(client_first_audio_ms) - first_pcm_ready_ms
            )
            enriched["transport_and_dispatch_residual_ms"] = residual_ms
            enriched["client_minus_worker_first_pcm_ready_ms"] = residual_ms
        if first_frame_enqueued_ms is not None:
            enriched["client_minus_worker_frame_enqueued_ms"] = (
                float(client_first_audio_ms) - first_frame_enqueued_ms
            )
        flushed_estimate = enriched.get("worker_first_frame_flushed_estimated_ms")
        if isinstance(flushed_estimate, (int, float)):
            enriched["client_minus_worker_frame_flushed_estimated_ms"] = (
                float(client_first_audio_ms) - float(flushed_estimate)
            )

    return enriched


def _metrics_by_event(
    worker_metrics: list[dict[str, object]],
    request_id: int,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for metric in worker_metrics:
        if metric.get("request_id") != request_id:
            continue
        event = metric.get("event")
        if isinstance(event, str) and event not in result:
            result[event] = metric
    return result


def _metric_number(
    metrics: dict[str, dict[str, object]],
    event: str,
    field: str,
) -> float | None:
    value = metrics.get(event, {}).get(field)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _set_if_number(
    target: dict[str, object],
    key: str,
    value: float | None,
) -> None:
    if value is not None:
        target[key] = value


def _copy_metric_number(
    target: dict[str, object],
    source: dict[str, object],
    source_key: str,
    target_key: str,
) -> None:
    value = source.get(source_key)
    if isinstance(value, (int, float)):
        target[target_key] = float(value)


def _copy_metric_int(
    target: dict[str, object],
    source: dict[str, object],
    source_key: str,
    target_key: str,
) -> None:
    value = source.get(source_key)
    if isinstance(value, (int, float)):
        target[target_key] = int(value)


def _copy_metric_bool(
    target: dict[str, object],
    source: dict[str, object],
    source_key: str,
    target_key: str,
) -> None:
    value = source.get(source_key)
    if isinstance(value, bool):
        target[target_key] = value


def _copy_metric_string(
    target: dict[str, object],
    source: dict[str, object],
    source_key: str,
    target_key: str,
) -> None:
    value = source.get(source_key)
    if isinstance(value, str):
        target[target_key] = value


def _median_request(requests: list[dict[str, object]]) -> dict[str, object] | None:
    if not requests:
        return None
    result: dict[str, object] = {"request_count": len(requests)}
    for key in (
        "first_audio_ms",
        "completed_ms",
        "audio_duration_ms",
        "real_time_factor",
        "inverse_rtf",
        "worker_first_pcm_ready_ms",
        "worker_first_frame_enqueued_ms",
        "worker_first_frame_flushed_estimated_ms",
        "first_frame_flush_ms",
        "first_frame_output_queue_ms",
        "first_chunk_steps",
        *_PHASE_KEYS,
    ):
        values = [
            float(cast(int | float, request[key]))
            for request in requests
            if isinstance(request.get(key), (int, float))
        ]
        if values:
            result[key] = statistics.median(values)
    return result


def _worker_metrics(stderr_text: str) -> list[dict[str, object]]:
    metrics = []
    for line in stderr_text.splitlines():
        if not line.startswith("qtb_metric "):
            continue
        try:
            metrics.append(json.loads(line.removeprefix("qtb_metric ")))
        except json.JSONDecodeError:
            continue
    return metrics


def _parse_cpu_list(value: str) -> list[int]:
    if not value.strip():
        return []
    cpus = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        cpus.append(int(item))
    return cpus


if __name__ == "__main__":
    raise SystemExit(main())
