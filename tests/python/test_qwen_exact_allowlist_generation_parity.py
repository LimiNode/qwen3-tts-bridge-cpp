from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "qwen_exact_allowlist_generation_parity.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "qwen_exact_allowlist_generation_parity", _SCRIPT_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class ExactAllowlistGenerationParityTests(unittest.TestCase):
    def test_compare_seed_requires_exact_trace_terminal_and_routes(self) -> None:
        pair = _MODULE._compare_seed(7, _eager_run(), _compiled_run())

        self.assertTrue(pair["passed"])
        self.assertTrue(pair["codec_trace_exact"])

    def test_compare_seed_rejects_non_exact_codec_trace(self) -> None:
        compiled = _compiled_run()
        compiled["generation_trace"]["codec_sha256"] = "b" * 64

        pair = _MODULE._compare_seed(7, _eager_run(), compiled)

        self.assertFalse(pair["passed"])
        self.assertFalse(pair["codec_trace_exact"])

    def test_eager_profile_uses_no_first_chunk_warmup_length(self) -> None:
        profile = {
            "model_path": "model",
            "device": "cuda",
            "dtype": "bfloat16",
            "attn_implementation": "sdpa",
            "max_seq_len": 2048,
            "max_audio_seconds_per_utterance": 60.0,
            "emit_every_frames": 8,
            "emit_chunk_schedule": [],
            "compiled_emit_chunk_schedule": [],
            "eager_emit_chunk_schedule": [],
            "decode_window_frames": 80,
            "prefill_backend": "eager",
            "prefill_compile_compat_mode": "none",
            "prefill_compile_lengths": [],
            "prefill_compile_on_miss": False,
            "prefill_unknown_shape_policy": "eager",
            "prefill_compile_policy": "diagnostic_dynamic",
            "prefill_allowlist_warmup_manifest": "",
            "prefill_allowlist_warmup_repeats": 3,
            "prefill_allowlist_max_entries": 6,
            "prefill_allowlist_max_abs_threshold": 0.0,
            "prefill_require_precompiled": False,
            "prefill_first_chunk_warmup": False,
            "prefill_first_chunk_warmup_length": None,
        }

        from scripts.qwen_tail_case_matrix import _create_engine

        engine = _create_engine(profile, "ryan")

        self.assertIsNone(engine._config.prefill_first_chunk_warmup_length)


def _eager_run() -> dict[str, object]:
    return {
        "execution_outcome": "completed",
        "generation_outcome": "eos",
        "first_chunk_route": {"prefill_backend_used": "eager"},
        "generation_trace": _trace(),
    }


def _compiled_run() -> dict[str, object]:
    return {
        "execution_outcome": "completed",
        "generation_outcome": "eos",
        "first_chunk_route": {
            "prefill_backend_used": "compile_reduce_overhead",
            "prefill_shape_policy": "compiled_allowlist",
            "prefill_shape_allowlist_hit": True,
            "prefill_compile_cache_hit": True,
            "prefill_compile_fallback": False,
            "prefill_shape_call_ordinal": 3,
        },
        "generation_trace": _trace(),
    }


def _trace() -> dict[str, object]:
    return {
        "codec_sha256": "a" * 64,
        "codec_frame_count": 8,
        "termination_reason": "eos",
    }


if __name__ == "__main__":
    unittest.main()
