import argparse
import unittest

from verify_packaged_worker import _expected_warmed_up, _worker_process_args


class VerifyPackagedWorkerTests(unittest.TestCase):
    def test_auto_warmup_expectation_matches_engine_contract(self) -> None:
        cases = (
            ("mock", False, True),
            ("qwen", False, False),
            ("qwen", True, True),
        )

        for engine, warmup_synthesis, expected in cases:
            with self.subTest(engine=engine, warmup_synthesis=warmup_synthesis):
                args = argparse.Namespace(
                    engine=engine,
                    warmup_synthesis=warmup_synthesis,
                    expect_warmed_up="auto",
                )

                self.assertIs(expected, _expected_warmed_up(args))

    def test_explicit_warmup_expectation_overrides_auto_contract(self) -> None:
        args = argparse.Namespace(
            engine="qwen",
            warmup_synthesis=False,
            expect_warmed_up="true",
        )
        self.assertTrue(_expected_warmed_up(args))

        args.expect_warmed_up = "false"
        self.assertFalse(_expected_warmed_up(args))

    def test_worker_prefix_args_precede_engine_command(self) -> None:
        args = argparse.Namespace(
            worker_prefix_arg=["-B", "-m", "qwen_tts_bridge_worker"],
            engine="mock",
            mock_chunks=1,
        )

        self.assertEqual(
            ["-B", "-m", "qwen_tts_bridge_worker", "mock", "--chunks", "1"],
            _worker_process_args(args),
        )


if __name__ == "__main__":
    unittest.main()
