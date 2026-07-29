import unittest

from scripts.semantic_trace_contract import validate_generation_trace


class SemanticTraceContractTests(unittest.TestCase):
    def test_accepts_complete_eos_trace(self) -> None:
        validate_generation_trace(
            {
                "codec_sha256": "a" * 64,
                "codec_frame_count": 94,
                "termination_reason": "eos",
                "terminal_token_id": 2150,
                "terminal_step_index": 94,
                "generated_steps": 94,
                "emitted_steps": 94,
                "hit_eos": True,
                "hit_max_new_tokens": False,
                "hit_max_seq_len": False,
            }
        )

    def test_accepts_complete_max_seq_len_trace(self) -> None:
        validate_generation_trace(
            {
                "codec_sha256": "b" * 64,
                "codec_frame_count": 2015,
                "termination_reason": "max_seq_len",
                "terminal_token_id": None,
                "terminal_step_index": 2014,
                "generated_steps": 2015,
                "emitted_steps": 2015,
                "hit_eos": False,
                "hit_max_new_tokens": False,
                "hit_max_seq_len": True,
            }
        )

    def test_rejects_conflicting_terminal_flags(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "exactly one terminal flag"):
            validate_generation_trace(
                {
                    "codec_sha256": "c" * 64,
                    "codec_frame_count": 2,
                    "termination_reason": "eos",
                    "terminal_token_id": 9,
                    "terminal_step_index": 2,
                    "generated_steps": 2,
                    "emitted_steps": 2,
                    "hit_eos": True,
                    "hit_max_new_tokens": False,
                    "hit_max_seq_len": True,
                }
            )

    def test_rejects_counter_mismatch(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "codec_frame_count"):
            validate_generation_trace(
                {
                    "codec_sha256": "d" * 64,
                    "codec_frame_count": 2,
                    "termination_reason": "max_new_tokens",
                    "terminal_token_id": None,
                    "terminal_step_index": 2,
                    "generated_steps": 3,
                    "emitted_steps": 3,
                    "hit_eos": False,
                    "hit_max_new_tokens": True,
                    "hit_max_seq_len": False,
                }
            )

    def test_rejects_invalid_eos_step_index(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "rejected EOS candidate"):
            validate_generation_trace(
                {
                    "codec_sha256": "e" * 64,
                    "codec_frame_count": 2,
                    "termination_reason": "eos",
                    "terminal_token_id": 9,
                    "terminal_step_index": 1,
                    "generated_steps": 2,
                    "emitted_steps": 2,
                    "hit_eos": True,
                    "hit_max_new_tokens": False,
                    "hit_max_seq_len": False,
                }
            )


if __name__ == "__main__":
    unittest.main()
