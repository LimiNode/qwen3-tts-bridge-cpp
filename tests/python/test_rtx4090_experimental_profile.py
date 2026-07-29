"""Validate the checked-in RTX 4090 experimental worker profile."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from qwen_tts_bridge_worker.config import QwenEngineConfig

_ROOT = Path(__file__).resolve().parents[2]


class Rtx4090ExperimentalProfileTests(unittest.TestCase):
    def test_profile_constructs_the_strict_allowlist_configuration(self) -> None:
        profile = json.loads(
            (
                _ROOT / "config" / "rtx4090-faster-customvoice-experimental.json"
            ).read_text(encoding="utf-8")
        )

        config = QwenEngineConfig(
            model_path=profile["model_path"],
            runtime_backend=profile["runtime_backend"],
            device=profile["device"],
            dtype=profile["dtype"],
            attn_implementation=profile["attn_implementation"],
            emit_every_frames=profile["emit_every_frames"],
            decode_window_frames=profile["decode_window_frames"],
            prefill_backend=profile["prefill_backend"],
            prefill_compile_compat_mode=profile["prefill_compile_compat_mode"],
            prefill_compile_lengths=tuple(profile["prefill_compile_lengths"]),
            prefill_compile_on_miss=profile["prefill_compile_on_miss"],
            prefill_unknown_shape_policy=profile["prefill_unknown_shape_policy"],
            prefill_compile_policy=profile["prefill_compile_policy"],
            prefill_allowlist_warmup_manifest=profile[
                "prefill_allowlist_warmup_manifest"
            ],
            prefill_allowlist_warmup_repeats=profile[
                "prefill_allowlist_warmup_repeats"
            ],
            prefill_allowlist_max_entries=profile["prefill_allowlist_max_entries"],
            prefill_allowlist_max_abs_threshold=profile[
                "prefill_allowlist_max_abs_threshold"
            ],
            prefill_require_precompiled=profile["prefill_require_precompiled"],
            prefill_first_chunk_warmup_enabled=profile["prefill_first_chunk_warmup"],
            prefill_first_chunk_warmup_length=profile[
                "prefill_first_chunk_warmup_length"
            ],
            collect_generation_trace=profile["collect_generation_trace"],
            profile_prefill=profile["profile_prefill"],
        )

        self.assertEqual(config.runtime_backend, "faster")
        self.assertEqual(config.prefill_compile_compat_mode, "strict_bf16_sdpa_v1")
        self.assertEqual(config.prefill_compile_policy, "exact_allowlist")
        self.assertFalse(config.prefill_compile_on_miss)
        self.assertTrue(config.prefill_require_precompiled)
        self.assertEqual(config.prefill_compile_lengths, (32, 29, 35, 34, 33, 30))

    def test_scheduler_profile_constructs_the_first_chunk_schedule(self) -> None:
        profile = json.loads(
            (
                _ROOT
                / "config"
                / "rtx4090-faster-customvoice-scheduler-6-8-12-experimental.json"
            ).read_text(encoding="utf-8")
        )

        config = QwenEngineConfig(
            model_path=profile["model_path"],
            runtime_backend=profile["runtime_backend"],
            device=profile["device"],
            dtype=profile["dtype"],
            attn_implementation=profile["attn_implementation"],
            emit_every_frames=profile["emit_every_frames"],
            emit_chunk_schedule=tuple(profile["emit_chunk_schedule"]),
        )

        self.assertEqual(config.emit_chunk_schedule, (6, 8, 12))
        self.assertEqual(config.emit_every_frames, 12)

    def test_launcher_uses_module_entry_point_and_profile_path(self) -> None:
        launcher = (
            _ROOT / "scripts" / "start-rtx4090-faster-customvoice.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("qwen_tts_bridge_worker", launcher)
        self.assertIn("rtx4090-faster-customvoice-experimental.json", launcher)
        self.assertIn("--prefill-require-precompiled", launcher)
        self.assertIn("--emit-chunk-schedule", launcher)


if __name__ == "__main__":
    unittest.main()
