"""Tests for route-aware canary manifest generation."""

from __future__ import annotations

import unittest

from scripts.create_route_aware_canary_manifests import _allowlist_manifest


class CreateRouteAwareCanaryManifestTests(unittest.TestCase):
    def test_extracts_verified_contract_from_release_profile(self) -> None:
        manifest = _allowlist_manifest(_profile(), "profile-v21-9d2a61ef")

        self.assertEqual([29, 30, 32, 33, 34, 35], manifest["compiled_lengths"])
        self.assertEqual([8, 8, 12], manifest["compiled_schedule"])
        self.assertEqual([8], manifest["eager_schedule"])

    def test_rejects_profile_with_compile_on_miss(self) -> None:
        profile = _profile()
        profile["prefill_compile_on_miss"] = True

        with self.assertRaisesRegex(RuntimeError, "disable compile-on-miss"):
            _allowlist_manifest(profile, "profile-v21-9d2a61ef")


def _profile() -> dict[str, object]:
    return {
        "prefill_compile_lengths": [32, 29, 35, 34, 33, 30],
        "compiled_emit_chunk_schedule": [8, 8, 12],
        "eager_emit_chunk_schedule": [8],
        "prefill_backend": "compile_reduce_overhead",
        "prefill_compile_policy": "exact_allowlist",
        "prefill_unknown_shape_policy": "eager",
        "prefill_compile_on_miss": False,
        "prefill_require_precompiled": True,
    }


if __name__ == "__main__":
    unittest.main()
