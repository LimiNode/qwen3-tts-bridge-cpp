import unittest

from benchmark_packaged_worker_restart import (
    _median_request,
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
                "event": "request_first_pcm_ready",
                "request_id": 8,
                "first_pcm_ready_ms": 1.0,
            },
        ]

        enriched = _with_request_pipeline_metrics(request, metrics)

        self.assertEqual(100.0, enriched["worker_first_pcm_ready_ms"])
        self.assertEqual(101.5, enriched["worker_first_frame_enqueued_ms"])
        self.assertEqual(103.75, enriched["worker_first_frame_flushed_estimated_ms"])
        self.assertEqual(23.0, enriched["client_minus_worker_first_pcm_ready_ms"])
        self.assertEqual(21.5, enriched["client_minus_worker_frame_enqueued_ms"])
        self.assertEqual(
            19.25,
            enriched["client_minus_worker_frame_flushed_estimated_ms"],
        )
        self.assertEqual(2.25, enriched["first_frame_output_writer_ms"])
        self.assertEqual(0.75, enriched["first_frame_flush_ms"])
        self.assertEqual(1.5, enriched["first_frame_output_queue_ms"])

    def test_median_request_includes_pipeline_fields(self) -> None:
        median = _median_request(
            [
                {
                    "first_audio_ms": 10.0,
                    "client_minus_worker_first_pcm_ready_ms": 3.0,
                },
                {
                    "first_audio_ms": 20.0,
                    "client_minus_worker_first_pcm_ready_ms": 5.0,
                },
            ]
        )

        self.assertIsNotNone(median)
        assert median is not None
        self.assertEqual(15.0, median["first_audio_ms"])
        self.assertEqual(4.0, median["client_minus_worker_first_pcm_ready_ms"])


if __name__ == "__main__":
    unittest.main()
