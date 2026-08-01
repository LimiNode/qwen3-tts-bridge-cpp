from __future__ import annotations

import unittest

from scripts.qwen_runtime_policy_v2 import _evidence_checks


class QwenRuntimePolicyV2Tests(unittest.TestCase):
    def test_accepts_matching_immutable_evidence(self) -> None:
        checks = _evidence_checks(_policy(), _holdout(), _candidate(), {"passed": True})

        self.assertTrue(all(checks.values()))

    def test_rejects_runtime_mismatch(self) -> None:
        candidate = _candidate()
        candidate["runtime"]["torch_version"] = "mismatch"

        checks = _evidence_checks(_policy(), _holdout(), candidate, {"passed": True})

        self.assertFalse(checks["torch_matches_ab"])


def _policy() -> dict[str, object]:
    return {"status": "frozen_for_one_measurement_holdout", "profile_sha256": "profile"}


def _runtime() -> dict[str, object]:
    return {
        "bridge_worker_source_bundle_sha256": "worker",
        "torch_version": "torch",
        "cuda_version": "cuda",
        "triton_windows_version": "triton",
        "faster_qwen3_tts_source": {"module_bundle_sha256": "faster"},
    }


def _holdout() -> dict[str, object]:
    return {
        "status": "completed",
        "corpus_split": "runtime_measurement_holdout",
        "profile": {"sha256": "profile"},
        "runtime": _runtime(),
        "engine_warmup": {"prefill_generation_prime_ready": True},
    }


def _candidate() -> dict[str, object]:
    return {"runtime": _runtime()}


if __name__ == "__main__":
    unittest.main()
