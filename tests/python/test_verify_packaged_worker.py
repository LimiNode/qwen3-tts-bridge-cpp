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

    def test_qwen_seed_mode_args_are_forwarded(self) -> None:
        args = argparse.Namespace(
            worker_prefix_arg=[],
            engine="qwen",
            model_path="models/qwen",
            runtime_backend="faster",
            device="cuda",
            dtype="auto",
            attn_implementation="",
            max_seq_len=2048,
            emit_every_frames=8,
            decode_window_frames=80,
            overlap_samples=0,
            enable_streaming_optimizations=False,
            no_compile=False,
            no_cuda_graphs=False,
            compile_mode="reduce-overhead",
            use_fast_codebook=False,
            no_compile_codebook_predictor=False,
            no_compile_talker=False,
            matmul_precision="",
            profile_prefill=True,
            no_sample=True,
            seed=4242,
            seed_mode="fixed",
            warmup_seed=9001,
            warmup_synthesis=False,
            warmup_synthesis_passes=1,
            warmup_unbounded_passes=0,
            warmup_max_output_chunks=None,
            warmup_text="Warmup.",
            warmup_language="English",
            warmup_speaker="ryan",
            warmup_instruction="",
            engine_startup_mode="engine_warmup",
        )

        worker_args = _worker_process_args(args)

        self.assertIn("--seed-mode", worker_args)
        self.assertIn("fixed", worker_args)
        self.assertIn("--warmup-seed", worker_args)
        self.assertIn("9001", worker_args)
        self.assertIn("--engine-startup-mode", worker_args)
        self.assertIn("engine_warmup", worker_args)
        self.assertIn("--profile-prefill", worker_args)
        self.assertIn("--no-sample", worker_args)


if __name__ == "__main__":
    unittest.main()
