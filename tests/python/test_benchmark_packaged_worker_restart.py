import argparse
import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from benchmark_packaged_worker_restart import (
    _append_line,
    _correlations,
    _gpu_poll_summary,
    _load_run_shapes,
    _median_request,
    _outlier_records,
    _paired_delta_residual_summary,
    _paired_delta_residuals,
    _phase_delta,
    _profile_validation_summary,
    _progress_line,
    _RequestGpuPoller,
    _run_shape_for_index,
    _shape_summary,
    _talker_forward_explained_outlier_summary,
    _validate_runtime_provenance,
    _with_request_pipeline_metrics,
    _worker_process_args_for_run,
    _write_json_file,
)


class BenchmarkPackagedWorkerRestartTests(unittest.TestCase):
    def test_request_pipeline_metrics_are_derived_from_worker_events(self) -> None:
        request = {
            "request_id": 7,
            "first_audio_ms": 123.0,
            "completed_ms": 500.0,
        }
        metrics = [
            {
                "event": "request_first_pcm_ready",
                "request_id": 7,
                "first_pcm_ready_ms": 100.0,
            },
            {
                "event": "request_first_frame_enqueued",
                "request_id": 7,
                "first_frame_enqueue_ms": 101.5,
            },
            {
                "event": "request_first_frame_flushed",
                "request_id": 7,
                "output_writer_ms": 2.25,
                "flush_ms": 0.75,
                "output_queue_ms": 1.5,
            },
            {
                "event": "request_first_chunk_engine_phases",
                "request_id": 7,
                "prefill_ms": 12.0,
                "ar_decode_ms": 80.0,
                "chunk_steps": 8,
                "ar_ms_per_step": 10.0,
                "codec_wrapper_residual_ms": 4.5,
                "pcm_convert_ms": 0.25,
                "next_wall_ms": 96.5,
                "text_token_count": 21,
                "instruction_token_count": 9,
                "prefill_sequence_length": 30,
                "talker_prefill_length": 42,
                "profile_schema_version": 3,
                "profile_path": "fast",
                "profile_request_role": "first_user",
                "profile_prefill_enabled": True,
                "profile_complete": True,
                "events_complete": True,
                "components_finite": True,
                "components_nonnegative": True,
                "all_component_streams_equal": True,
                "prefill_total_gpu_ms": 11.0,
                "talker_forward_gpu_ms": 1.0,
                "first_sample_gpu_ms": 6.0,
                "prefill_kv_gpu_ms": 3.0,
                "generation_state_gpu_ms": 1.0,
                "prefill_to_sync_gpu_ms": 0.0,
                "prefill_sync_wait_ms": 1.5,
                "prefill_gpu_component_sum_ms": 11.0,
                "prefill_gpu_partition_error_ms": 0.0,
                "prefill_gpu_accounting_error_ms": 0.0,
                "talker_forward_gpu_stream_id": 1234,
            },
            {
                "event": "request_first_pcm_ready",
                "request_id": 8,
                "first_pcm_ready_ms": 1.0,
            },
        ]

        enriched = _with_request_pipeline_metrics(request, metrics)

        self.assertEqual(100.0, enriched["worker_first_pcm_ready_ms"])
        self.assertEqual(101.5, enriched["worker_first_frame_enqueued_ms"])
        self.assertEqual(103.75, enriched["worker_first_frame_flushed_estimated_ms"])
        self.assertEqual(23.0, enriched["transport_and_dispatch_residual_ms"])
        self.assertEqual(23.0, enriched["client_minus_worker_first_pcm_ready_ms"])
        self.assertEqual(21.5, enriched["client_minus_worker_frame_enqueued_ms"])
        self.assertEqual(
            19.25,
            enriched["client_minus_worker_frame_flushed_estimated_ms"],
        )
        self.assertEqual(2.25, enriched["first_frame_output_writer_ms"])
        self.assertEqual(0.75, enriched["first_frame_flush_ms"])
        self.assertEqual(1.5, enriched["first_frame_output_queue_ms"])
        self.assertEqual(12.0, enriched["first_chunk_prefill_ms"])
        self.assertEqual(80.0, enriched["first_chunk_ar_decode_ms"])
        self.assertEqual(8.0, enriched["first_chunk_steps"])
        self.assertEqual(10.0, enriched["first_chunk_ar_ms_per_step"])
        self.assertEqual(4.5, enriched["first_chunk_codec_wrapper_residual_ms"])
        self.assertEqual(0.25, enriched["first_chunk_pcm_convert_ms"])
        self.assertEqual(21.0, enriched["first_chunk_text_token_count"])
        self.assertEqual(9.0, enriched["first_chunk_instruction_token_count"])
        self.assertEqual(30.0, enriched["first_chunk_prefill_sequence_length"])
        self.assertEqual(42.0, enriched["first_chunk_talker_prefill_length"])
        self.assertEqual(3, enriched["first_chunk_profile_schema_version"])
        self.assertEqual("fast", enriched["first_chunk_profile_path"])
        self.assertEqual("first_user", enriched["first_chunk_profile_request_role"])
        self.assertTrue(enriched["first_chunk_profile_prefill_enabled"])
        self.assertTrue(enriched["first_chunk_profile_complete"])
        self.assertTrue(enriched["first_chunk_events_complete"])
        self.assertTrue(enriched["first_chunk_components_finite"])
        self.assertTrue(enriched["first_chunk_components_nonnegative"])
        self.assertTrue(enriched["first_chunk_all_component_streams_equal"])
        self.assertEqual(11.0, enriched["first_chunk_prefill_total_gpu_ms"])
        self.assertEqual(1.0, enriched["first_chunk_talker_forward_gpu_ms"])
        self.assertEqual(6.0, enriched["first_chunk_first_sample_gpu_ms"])
        self.assertEqual(3.0, enriched["first_chunk_prefill_kv_gpu_ms"])
        self.assertEqual(1.0, enriched["first_chunk_generation_state_gpu_ms"])
        self.assertEqual(1.5, enriched["first_chunk_prefill_sync_wait_ms"])
        self.assertEqual(11.0, enriched["first_chunk_prefill_gpu_component_sum_ms"])
        self.assertEqual(0.0, enriched["first_chunk_prefill_gpu_partition_error_ms"])
        self.assertEqual(0.0, enriched["first_chunk_prefill_gpu_accounting_error_ms"])
        self.assertEqual(1234, enriched["first_chunk_talker_forward_gpu_stream_id"])

    def test_median_request_includes_pipeline_fields(self) -> None:
        median = _median_request(
            [
                {
                    "first_audio_ms": 10.0,
                    "transport_and_dispatch_residual_ms": 3.0,
                    "client_minus_worker_first_pcm_ready_ms": 3.0,
                },
                {
                    "first_audio_ms": 20.0,
                    "transport_and_dispatch_residual_ms": 5.0,
                    "client_minus_worker_first_pcm_ready_ms": 5.0,
                },
            ]
        )

        self.assertIsNotNone(median)
        assert median is not None
        self.assertEqual(15.0, median["first_audio_ms"])
        self.assertEqual(4.0, median["transport_and_dispatch_residual_ms"])
        self.assertEqual(4.0, median["client_minus_worker_first_pcm_ready_ms"])

    def test_phase_delta_compares_first_request_to_steady_median(self) -> None:
        delta = _phase_delta(
            {
                "transport_and_dispatch_residual_ms": 5.0,
                "first_chunk_prefill_ms": 120.0,
            },
            {
                "transport_and_dispatch_residual_ms": 3.0,
                "first_chunk_prefill_ms": 100.0,
            },
        )

        self.assertEqual(2.0, delta["transport_and_dispatch_residual_ms"])
        self.assertEqual(20.0, delta["first_chunk_prefill_ms"])

    def test_progress_line_reports_last_run_numbers(self) -> None:
        line = _progress_line(
            done=2,
            total=10,
            started_at=0.0,
            run_summary={
                "first_request": {"first_audio_ms": 400.25},
                "steady_request_median": {"first_audio_ms": 380.0},
                "paired_delta_first_audio_ms": 20.25,
            },
        )

        self.assertIn("progress 2/10", line)
        self.assertIn("last_first_audio_ms=400.2", line)
        self.assertIn("last_steady_first_audio_ms=380.0", line)
        self.assertIn("last_delta_first_audio_ms=20.2", line)

    def test_write_json_file_replaces_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "partial.json"

            _write_json_file(path, {"runs": [{"run_index": 1}]})
            _write_json_file(path, {"runs": [{"run_index": 2}]})

            self.assertEqual({"runs": [{"run_index": 2}]}, json.loads(path.read_text()))
            self.assertFalse(path.with_name("partial.json.tmp").exists())

    def test_append_line_writes_plain_progress_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "progress.txt"

            _append_line(path, "progress 1/2")
            _append_line(path, "progress 2/2")

            self.assertEqual("progress 1/2\nprogress 2/2\n", path.read_text())

    def test_worker_process_args_for_run_offsets_qwen_seeds(self) -> None:
        worker_args = _worker_process_args_for_run(
            _qwen_args(
                seed=4242,
                warmup_seed=9001,
                run_seed_step=100,
                run_warmup_seed_step=7,
            ),
            run_index=3,
        )

        self.assertEqual("4442", _value_after(worker_args, "--seed"))
        self.assertEqual("9015", _value_after(worker_args, "--warmup-seed"))

    def test_worker_process_args_for_run_can_warm_up_from_shape(self) -> None:
        args = _qwen_args(
            seed=None,
            warmup_seed=None,
            run_seed_step=0,
            run_warmup_seed_step=0,
        )
        args.warmup_from_run_shape = True

        worker_args = _worker_process_args_for_run(
            args,
            run_index=1,
            run_shape={
                "text": "Bucket warmup prompt.",
                "language": "English",
                "speaker": "ryan",
                "instruction": "Speak warmly.",
            },
        )

        self.assertEqual(
            "Bucket warmup prompt.",
            _value_after(worker_args, "--warmup-text"),
        )
        self.assertEqual("English", _value_after(worker_args, "--warmup-language"))
        self.assertEqual("ryan", _value_after(worker_args, "--warmup-speaker"))
        self.assertEqual(
            "Speak warmly.",
            _value_after(worker_args, "--warmup-instruction"),
        )

    def test_load_run_shapes_reads_jsonl_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "shapes.jsonl"
            path.write_text(
                '{"label":"short","text":"Short.","language":"English"}\n'
                '{"label":"long","text":"Long text.","speaker":"ryan"}\n',
                encoding="utf-8",
            )

            shapes = _load_run_shapes(path)

        self.assertEqual("short", shapes[0]["label"])
        self.assertEqual("English", shapes[0]["language"])
        self.assertEqual("", shapes[0]["speaker"])
        self.assertEqual("long", shapes[1]["label"])
        self.assertEqual("ryan", shapes[1]["speaker"])

    def test_load_run_shapes_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "shapes.jsonl"
            path.write_text(
                '\ufeff{"label":"short","text":"Short."}\n',
                encoding="utf-8",
            )

            shapes = _load_run_shapes(path)

        self.assertEqual("short", shapes[0]["label"])

    def test_run_shape_for_index_uses_schedule_and_counts_characters(self) -> None:
        shape = _run_shape_for_index(
            argparse.Namespace(
                text="default",
                language="auto",
                speaker="",
                instruction="",
            ),
            [{"label": "short", "text": "abcd", "language": "English"}],
            1,
        )

        self.assertEqual("short", shape["label"])
        self.assertEqual(4, shape["text_characters"])

    def test_shape_summary_groups_runs(self) -> None:
        summary = _shape_summary(
            [
                _summary_run("short", delta=1.0, first_audio=10.0),
                _summary_run("short", delta=3.0, first_audio=12.0),
                _summary_run("long", delta=25.0, first_audio=20.0),
                _summary_run("long", delta=-30.0, first_audio=20.0),
            ]
        )

        short = cast(dict[str, object], summary["short"])
        long = cast(dict[str, object], summary["long"])
        short_first = cast(dict[str, object], short["first_request"])
        short_first_audio = cast(dict[str, object], short_first["first_audio_ms"])

        self.assertEqual(2, short["runs"])
        self.assertEqual(1, long["slow_delta_count"])
        self.assertEqual(1, long["positive_tail_count"])
        self.assertEqual(1, long["negative_tail_count"])
        self.assertEqual(2, long["unstable_count"])
        self.assertEqual(
            11.0,
            short_first_audio["median"],
        )

    def test_shape_summary_uses_configured_slow_delta_threshold(self) -> None:
        summary = _shape_summary(
            [_summary_run("long", delta=25.0, first_audio=20.0)],
            threshold_ms=30.0,
        )

        long = cast(dict[str, object], summary["long"])
        self.assertEqual(0, long["slow_delta_count"])

    def test_outlier_records_include_phase_and_shape_context(self) -> None:
        outliers = _outlier_records(
            [_summary_run("long", delta=25.0, first_audio=20.0)],
            threshold_ms=20.0,
        )

        self.assertEqual(1, len(outliers))
        outlier = outliers[0]
        shape = cast(dict[str, object], outlier["shape"])
        phase_delta = cast(dict[str, object], outlier["paired_phase_delta"])

        self.assertEqual("long", shape["label"])
        self.assertEqual("positive", outlier["tail_kind"])
        self.assertEqual(
            5.0,
            phase_delta["first_chunk_prefill_ms"],
        )

    def test_outlier_records_include_negative_tail(self) -> None:
        outliers = _outlier_records(
            [_summary_run("long", delta=-25.0, first_audio=20.0)],
            threshold_ms=20.0,
        )

        self.assertEqual(1, len(outliers))
        self.assertEqual("negative", outliers[0]["tail_kind"])
        self.assertEqual(-25.0, outliers[0]["paired_delta_first_audio_ms"])

    def test_correlations_report_pearson_for_phase_delta(self) -> None:
        correlations = _correlations(
            [
                _summary_run("short", delta=1.0, first_audio=10.0),
                _summary_run("medium", delta=2.0, first_audio=20.0),
                _summary_run("long", delta=3.0, first_audio=30.0),
            ]
        )

        prefill = cast(
            dict[str, object],
            correlations["total_delta_vs_prefill_delta"],
        )
        self.assertAlmostEqual(
            1.0,
            cast(float, prefill["pearson_r"]),
        )
        token_count = cast(
            dict[str, object],
            correlations["total_delta_vs_text_token_count"],
        )
        self.assertEqual(3, token_count["count"])

    def test_paired_delta_residuals_subtract_prefill_and_account_wall_time(
        self,
    ) -> None:
        residuals = _paired_delta_residuals(
            25.0,
            {
                "first_chunk_prefill_ms": 7.0,
                "first_chunk_first_sample_gpu_ms": 4.0,
                "first_chunk_talker_forward_gpu_ms": 9.0,
                "first_chunk_prefill_kv_gpu_ms": 2.0,
                "first_chunk_next_wall_ms": 23.0,
                "transport_and_dispatch_residual_ms": 1.5,
            },
        )

        self.assertEqual(18.0, residuals["delta_without_prefill_ms"])
        self.assertEqual(21.0, residuals["delta_without_first_sample_ms"])
        self.assertEqual(16.0, residuals["delta_without_talker_forward_ms"])
        self.assertEqual(16.0, residuals["absolute_delta_without_talker_forward_ms"])
        self.assertEqual(9.0, residuals["talker_explained_ms"])
        self.assertEqual(16.0, residuals["positive_unexplained_without_talker_ms"])
        self.assertEqual(0.36, residuals["talker_explained_fraction"])
        self.assertEqual(23.0, residuals["delta_without_prefill_kv_ms"])
        self.assertEqual(24.5, residuals["phase_accounted_delta_ms"])
        self.assertEqual(0.5, residuals["phase_accounting_error_ms"])

    def test_paired_delta_residual_summary_reports_distribution(self) -> None:
        summary = _paired_delta_residual_summary(
            [
                {
                    "paired_delta_residuals": {
                        "delta_without_prefill_ms": 3.0,
                        "phase_accounting_error_ms": 0.5,
                    }
                },
                {
                    "paired_delta_residuals": {
                        "delta_without_prefill_ms": 5.0,
                        "phase_accounting_error_ms": -0.5,
                    }
                },
            ]
        )

        without_prefill = cast(dict[str, object], summary["delta_without_prefill_ms"])
        accounting_error = cast(dict[str, object], summary["phase_accounting_error_ms"])
        self.assertEqual(4.0, without_prefill["median"])
        self.assertEqual(0.0, accounting_error["median"])

    def test_profile_validation_summary_reports_completeness(self) -> None:
        summary = _profile_validation_summary(
            [
                {
                    "first_chunk_profile_prefill_enabled": True,
                    "first_chunk_profile_complete": True,
                    "first_chunk_events_complete": True,
                    "first_chunk_components_finite": True,
                    "first_chunk_components_nonnegative": True,
                    "first_chunk_all_component_streams_equal": True,
                    "first_chunk_profile_path": "fast",
                    "first_chunk_profile_request_role": "first_user",
                },
                {
                    "first_chunk_profile_prefill_enabled": True,
                    "first_chunk_profile_complete": False,
                    "first_chunk_events_complete": False,
                    "first_chunk_components_finite": True,
                    "first_chunk_components_nonnegative": True,
                    "first_chunk_all_component_streams_equal": False,
                    "first_chunk_profile_path": "parity",
                    "first_chunk_profile_request_role": "steady",
                },
                {
                    "first_chunk_profile_prefill_enabled": False,
                },
            ]
        )

        self.assertEqual(2, summary["profiled_first_chunk_count"])
        self.assertEqual(1, summary["profile_complete_count"])
        self.assertEqual(0.5, summary["profile_complete_fraction"])
        self.assertEqual(1, summary["all_component_streams_equal_count"])
        self.assertEqual({"fast": 1, "parity": 1}, summary["profile_paths"])
        self.assertEqual(
            {"first_user": 1, "steady": 1},
            summary["profile_request_roles"],
        )

    def test_talker_forward_explained_outlier_summary_counts_positive_tails(
        self,
    ) -> None:
        summary = _talker_forward_explained_outlier_summary(
            [
                {
                    "paired_delta_first_audio_ms": 25.0,
                    "paired_delta_residuals": {
                        "positive_unexplained_without_talker_ms": 10.0,
                    },
                },
                {
                    "paired_delta_first_audio_ms": 30.0,
                    "paired_delta_residuals": {
                        "positive_unexplained_without_talker_ms": 25.0,
                    },
                },
                {
                    "paired_delta_first_audio_ms": -30.0,
                    "paired_delta_residuals": {
                        "positive_unexplained_without_talker_ms": 0.0,
                    },
                },
            ],
            threshold_ms=20.0,
        )

        self.assertEqual(2, summary["positive_outlier_count"])
        self.assertEqual(1, summary["explained_by_talker_forward_count"])
        self.assertEqual(0.5, summary["explained_by_talker_forward_fraction"])

    def test_gpu_poll_summary_extracts_first_gpu_maxima(self) -> None:
        summary = _gpu_poll_summary(
            [
                {
                    "snapshot": {
                        "available": True,
                        "gpus": [
                            {
                                "utilization.gpu": "10",
                                "power.draw": "120.5",
                                "clocks.sm": "2700",
                                "clocks.mem": "10501",
                                "temperature.gpu": "42",
                            }
                        ],
                    }
                },
                {
                    "snapshot": {
                        "available": True,
                        "gpus": [
                            {
                                "utilization.gpu": "87",
                                "power.draw": "301.25",
                                "clocks.sm": "2715",
                                "clocks.mem": "10501",
                                "temperature.gpu": "48",
                            }
                        ],
                    }
                },
            ]
        )

        self.assertEqual(2, summary["available_sample_count"])
        self.assertEqual(87.0, summary["max_utilization_gpu"])
        self.assertEqual(301.25, summary["max_power_draw"])
        self.assertEqual(2715.0, summary["max_clocks_sm"])
        self.assertEqual(48.0, summary["max_temperature_gpu"])

    def test_gpu_poller_returns_none_when_disabled(self) -> None:
        poller = _RequestGpuPoller(0.0)

        poller.start()

        self.assertIsNone(poller.stop())

    def test_validate_runtime_provenance_requires_verified_faster_wheel(self) -> None:
        args = argparse.Namespace(engine="qwen", runtime_backend="faster")

        with self.assertRaisesRegex(RuntimeError, "not verified"):
            _validate_runtime_provenance(
                args,
                {
                    "imports": {
                        "faster_qwen3_tts": {
                            "distribution": {
                                "retained_wheel_match_verified": None,
                            }
                        }
                    }
                },
            )

    def test_validate_runtime_provenance_accepts_verified_faster_wheel(self) -> None:
        _validate_runtime_provenance(
            argparse.Namespace(engine="qwen", runtime_backend="faster"),
            {
                "imports": {
                    "faster_qwen3_tts": {
                        "distribution": {
                            "retained_wheel_match_verified": True,
                        }
                    }
                }
            },
        )


def _qwen_args(
    *,
    seed: int | None,
    warmup_seed: int | None,
    run_seed_step: int,
    run_warmup_seed_step: int,
) -> argparse.Namespace:
    return argparse.Namespace(
        worker_prefix_arg=["-B"],
        engine="qwen",
        model_path="models/qwen",
        runtime_backend="faster",
        device="cuda",
        dtype="auto",
        max_seq_len=2048,
        emit_every_frames=8,
        decode_window_frames=80,
        overlap_samples=0,
        attn_implementation="",
        enable_streaming_optimizations=False,
        no_compile=False,
        no_cuda_graphs=False,
        compile_mode="reduce-overhead",
        use_fast_codebook=False,
        no_compile_codebook_predictor=False,
        no_compile_talker=False,
        matmul_precision="",
        no_sample=False,
        seed=seed,
        seed_mode="request_id",
        warmup_seed=warmup_seed,
        run_seed_step=run_seed_step,
        run_warmup_seed_step=run_warmup_seed_step,
        warmup_synthesis=True,
        warmup_synthesis_passes=1,
        warmup_unbounded_passes=0,
        warmup_max_output_chunks=None,
        warmup_text="Warmup.",
        warmup_language="English",
        warmup_speaker="ryan",
        warmup_instruction="",
        warmup_from_run_shape=False,
        engine_startup_mode="auto",
        request_gpu_poll_interval_ms=0.0,
    )


def _value_after(args: list[str], key: str) -> str:
    return args[args.index(key) + 1]


def _summary_run(label: str, *, delta: float, first_audio: float) -> dict[str, object]:
    return {
        "run_index": 1,
        "shape": {
            "label": label,
            "text": f"{label} text",
            "language": "English",
            "speaker": "ryan",
            "instruction": "",
            "text_characters": len(label),
        },
        "steady_request_median": {"first_audio_ms": first_audio - delta},
        "paired_delta_first_audio_ms": delta,
        "paired_phase_delta": {
            "first_chunk_prefill_ms": delta / 5.0,
            "first_chunk_ar_decode_ms": delta / 10.0,
            "first_chunk_talker_forward_gpu_ms": delta / 2.0,
            "first_chunk_codec_wrapper_residual_ms": delta / 20.0,
        },
        "first_request": {
            "first_audio_ms": first_audio,
            "first_chunk_text_token_count": len(label) * 2,
            "first_chunk_prefill_sequence_length": len(label) * 2 + 10,
        },
        "gpu": {},
        "affinity": {},
    }


if __name__ == "__main__":
    unittest.main()
