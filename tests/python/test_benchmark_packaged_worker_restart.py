import argparse
import json
import tempfile
import unittest
from pathlib import Path

from benchmark_packaged_worker_restart import (
    _append_line,
    _median_request,
    _phase_delta,
    _progress_line,
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
        engine_startup_mode="auto",
    )


def _value_after(args: list[str], key: str) -> str:
    return args[args.index(key) + 1]


if __name__ == "__main__":
    unittest.main()
