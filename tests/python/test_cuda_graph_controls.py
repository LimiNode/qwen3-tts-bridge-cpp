"""Tests for explicit CUDA-graph control boundaries."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from qwen_tts_bridge_worker.cli import build_parser
from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine.qwen_engine import _runtime_execution_policy_fields


class CudaGraphControlTests(unittest.TestCase):
    def test_faster_policy_does_not_claim_control_of_runtime_cuda_graphs(self) -> None:
        fields = _runtime_execution_policy_fields(
            QwenEngineConfig(model_path="models/qwen", runtime_backend="faster")
        )

        self.assertEqual("faster", fields["runtime_backend"])
        self.assertEqual("not_applicable", fields["bridge_cuda_graph_control"])
        self.assertTrue(fields["runtime_internal_cuda_graphs_may_be_enabled"])

    def test_upstream_policy_reports_the_bridge_graph_setting(self) -> None:
        fields = _runtime_execution_policy_fields(
            QwenEngineConfig(
                model_path="models/qwen",
                runtime_backend="upstream",
                enable_streaming_optimizations=True,
                use_cuda_graphs=False,
            )
        )

        self.assertFalse(fields["bridge_cuda_graph_control"])
        self.assertFalse(fields["runtime_internal_cuda_graphs_may_be_enabled"])

    def test_qwen_help_names_the_fasterqwen_limit(self) -> None:
        parser = build_parser()
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit):
            parser.parse_args(["qwen", "--help"])

        self.assertIn(
            "FasterQwen may still capture",
            output.getvalue(),
        )
        self.assertIn(
            "internal CUDA graphs",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
