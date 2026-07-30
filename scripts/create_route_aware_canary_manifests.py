"""Create pinned canary manifests from an internal route-aware profile."""

from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COMPILED_ROUTE = "compiled_allowlist"
_COMPILED_BACKEND = "compile_reduce_overhead"
_COMPILED_SCHEDULE = [8, 8, 12]
_EAGER_ROUTE = "eager_unknown"
_EAGER_BACKEND = "eager"
_EAGER_SCHEDULE = [8]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--runtime-profile-id", required=True)
    parser.add_argument("--faster-wheel-sha256", required=True)
    parser.add_argument("--qwen-commit", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--torch-version", required=True)
    parser.add_argument("--cuda-version", required=True)
    parser.add_argument("--bridge-commit", default=_git_head())
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    profile = _load_profile(args.profile)
    allowlist = _allowlist_manifest(profile, args.runtime_profile_id)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    allowlist_path = args.output_directory / "compiled-allowlist-manifest.json"
    _write_json(allowlist_path, allowlist)
    runtime_profile = {
        "manifest_schema_version": 1,
        "runtime_profile_id": args.runtime_profile_id,
        "bridge_commit": args.bridge_commit,
        "faster_wheel_sha256": args.faster_wheel_sha256,
        "qwen_commit": args.qwen_commit,
        "model_revision": args.model_revision,
        "torch_version": args.torch_version,
        "cuda_version": args.cuda_version,
        "compiled_allowlist_manifest_sha256": _sha256(allowlist_path),
    }
    profile_path = args.output_directory / "runtime-profile-manifest.json"
    _write_json(profile_path, runtime_profile)
    print(
        json.dumps(
            {
                "runtime_profile_manifest": str(profile_path),
                "compiled_allowlist_manifest": str(allowlist_path),
                "runtime_profile_id": args.runtime_profile_id,
            },
            sort_keys=True,
        )
    )
    return 0


def _load_profile(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("route-aware profile must contain a JSON object")
    return value


def _allowlist_manifest(
    profile: dict[str, object], runtime_profile_id: str
) -> dict[str, object]:
    lengths = profile.get("prefill_compile_lengths")
    if not isinstance(lengths, list) or not all(
        isinstance(length, int) and not isinstance(length, bool) and length > 0
        for length in lengths
    ):
        raise RuntimeError("profile prefill_compile_lengths must be positive integers")
    if profile.get("compiled_emit_chunk_schedule") != _COMPILED_SCHEDULE:
        raise RuntimeError("profile must use the compiled 8/8/12 schedule")
    if profile.get("eager_emit_chunk_schedule") != _EAGER_SCHEDULE:
        raise RuntimeError("profile must use the eager fixed-8 schedule")
    if profile.get("prefill_backend") != _COMPILED_BACKEND:
        raise RuntimeError("profile must use compile_reduce_overhead prefill")
    if profile.get("prefill_compile_policy") != "exact_allowlist":
        raise RuntimeError("profile must use the exact allowlist policy")
    if profile.get("prefill_unknown_shape_policy") != "eager":
        raise RuntimeError("profile must use eager unknown-shape fallback")
    if profile.get("prefill_compile_on_miss") is not False:
        raise RuntimeError("profile must disable compile-on-miss")
    if profile.get("prefill_require_precompiled") is not True:
        raise RuntimeError("profile must require precompiled allowlist entries")
    return {
        "manifest_schema_version": 1,
        "runtime_profile_id": runtime_profile_id,
        "compiled_lengths": sorted(lengths),
        "compiled_route": _COMPILED_ROUTE,
        "compiled_backend": _COMPILED_BACKEND,
        "compiled_schedule": _COMPILED_SCHEDULE,
        "eager_route": _EAGER_ROUTE,
        "eager_backend": _EAGER_BACKEND,
        "eager_schedule": _EAGER_SCHEDULE,
    }


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
