import unittest

from scripts.faster_qwen_benchmark_accounting import (
    PlaybackChunk,
    simulate_playback,
    validate_emitted_steps,
    validate_pending_steps,
    validate_reported_steps,
)


class FasterBenchmarkAccountingTest(unittest.TestCase):
    def test_validate_reported_steps_accepts_matching_shape(self) -> None:
        validate_reported_steps(reported_steps=4, actual_steps=4)

    def test_validate_reported_steps_rejects_metadata_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "producer chunk step mismatch"):
            validate_reported_steps(reported_steps=8, actual_steps=4)

    def test_validate_pending_steps_rejects_lost_remainder(self) -> None:
        with self.assertRaisesRegex(ValueError, "pending chunk step mismatch"):
            validate_pending_steps(pending_steps=12, combined_steps=8)

    def test_validate_emitted_steps_rejects_tail_loss(self) -> None:
        with self.assertRaisesRegex(ValueError, "adaptive chunk accounting mismatch"):
            validate_emitted_steps(generated_steps=13, emitted_steps=12)

    def test_playback_simulation_reports_second_margin(self) -> None:
        result = simulate_playback(
            [
                PlaybackChunk(arrival_ms=300.0, audio_ms=320.0),
                PlaybackChunk(arrival_ms=610.0, audio_ms=960.0),
            ],
            transport_reserve_ms=0.0,
        )

        self.assertEqual(result.underrun_count, 0)
        self.assertEqual(result.minimum_buffer_ms, 10.0)
        self.assertEqual(result.minimum_reserve_margin_ms, 10.0)
        self.assertEqual(result.second_arrival_margin_ms, 10.0)
        self.assertEqual(result.second_arrival_reserve_margin_ms, 10.0)

    def test_playback_simulation_counts_underrun(self) -> None:
        result = simulate_playback(
            [
                PlaybackChunk(arrival_ms=300.0, audio_ms=320.0),
                PlaybackChunk(arrival_ms=621.0, audio_ms=960.0),
            ],
            transport_reserve_ms=0.0,
        )

        self.assertEqual(result.underrun_count, 1)
        self.assertEqual(result.minimum_buffer_ms, -1.0)
        self.assertEqual(result.minimum_reserve_margin_ms, -1.0)
        self.assertEqual(result.second_arrival_margin_ms, -1.0)
        self.assertEqual(result.second_arrival_reserve_margin_ms, -1.0)

    def test_playback_simulation_reports_transport_reserve_violation(self) -> None:
        result = simulate_playback(
            [
                PlaybackChunk(arrival_ms=300.0, audio_ms=320.0),
                PlaybackChunk(arrival_ms=610.0, audio_ms=960.0),
            ],
            transport_reserve_ms=50.0,
        )

        self.assertEqual(result.underrun_count, 0)
        self.assertEqual(result.reserve_violation_count, 1)
        self.assertEqual(result.second_arrival_margin_ms, 10.0)
        self.assertEqual(result.second_arrival_reserve_margin_ms, -40.0)


if __name__ == "__main__":
    unittest.main()
