import unittest

from benchmark_packaged_worker_restart import (
    _median_request,
    _phase_delta,
    _with_request_pipeline_metrics,
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


if __name__ == "__main__":
    unittest.main()
