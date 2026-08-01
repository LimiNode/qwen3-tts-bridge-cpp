from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "qwen_tail_case_matrix.py"
)
_SPEC = importlib.util.spec_from_file_location("qwen_tail_case_matrix", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class QwenTailCaseMatrixTests(unittest.TestCase):
    def test_mode_summary_separates_safety_outcome_and_tail_metrics(self) -> None:
        summary = _MODULE._mode_summary(
            [
                {
                    "execution_outcome": "completed",
                    "generation_outcome": "eos",
                    "audio_seconds": 10.0,
                    "first_audio_ms": 250.0,
                    "codec_frame_count": 100,
                },
                {
                    "execution_outcome": "failed",
                    "generation_outcome": "safety_duration_limit",
                    "audio_seconds": 60.0,
                    "first_audio_ms": 300.0,
                    "codec_frame_count": 600,
                },
            ]
        )

        self.assertEqual(
            {"completed": 1, "failed": 1},
            summary["execution_outcomes"],
        )
        self.assertEqual(
            {"eos": 1, "safety_duration_limit": 1},
            summary["generation_outcomes"],
        )
        self.assertEqual(57.5, summary["audio_seconds"]["p95"])

    def test_trace_outcome_prefers_eos(self) -> None:
        self.assertEqual("eos", _MODULE._trace_outcome({"hit_eos": True}))
        self.assertEqual(
            "max_seq_len",
            _MODULE._trace_outcome({"hit_max_seq_len": True}),
        )


if __name__ == "__main__":
    unittest.main()
