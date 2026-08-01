"""Fail closed before launching a sealed internal FasterQwen profile."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    profile_bytes = args.profile.read_bytes()
    profile = _load_object(profile_bytes, "profile")
    policy_path = _policy_path(args.profile, profile)
    policy = _load_object(policy_path.read_bytes(), "evidence policy")
    repo_root = args.profile.parents[1]
    report = _validate(profile, policy, _runtime(repo_root), repo_root)
    profile_sha256 = _sha256(profile_bytes)
    if policy.get("profile_sha256") != profile_sha256:
        report["failures"].append("profile SHA does not match policy")
    report["profile_sha256"] = profile_sha256
    report["evidence_policy"] = policy_path.name
    report["acceptance_pass"] = not report["failures"]
    payload = _json_bytes(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    print(payload.decode("utf-8"), end="")
    return 0 if report["acceptance_pass"] else 1


def _validate(
    profile: dict[str, object],
    policy: dict[str, object],
    runtime: dict[str, object],
    repo_root: Path,
) -> dict[str, object]:
    failures: list[str] = []
    if profile.get("profile_status") != "internal_opt_in_only":
        failures.append("profile is not internal_opt_in_only")
    if policy.get("runtime_policy_schema_version") != 2:
        failures.append("runtime policy schema is unsupported")
    if policy.get("status") != "internal_opt_in_only":
        failures.append("runtime policy is not internal_opt_in_only")
    _compare("profile", profile, _object(policy, "profile_contract"), failures)
    _compare("runtime", runtime, _object(policy, "runtime_contract"), failures)
    _validate_evidence(repo_root, _object(policy, "evidence_files"), failures)
    return {"failures": failures, "runtime": runtime}


def _compare(
    label: str,
    actual: dict[str, object],
    expected: dict[str, object],
    failures: list[str],
) -> None:
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            failures.append(f"{label}.{key} does not match policy")


def _validate_evidence(
    repo_root: Path,
    files: dict[str, object],
    failures: list[str],
) -> None:
    for relative_path, expected_sha256 in files.items():
        if not isinstance(relative_path, str) or not isinstance(expected_sha256, str):
            failures.append("evidence file policy is invalid")
            continue
        path = repo_root / relative_path
        if not path.is_file():
            failures.append(f"evidence file is missing: {relative_path}")
        elif _sha256(path.read_bytes()) != expected_sha256:
            failures.append(f"evidence file SHA does not match: {relative_path}")


def _runtime(repo_root: Path) -> dict[str, object]:
    torch = importlib.import_module("torch")
    faster = importlib.import_module("faster_qwen3_tts")
    gpu = torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None
    return {
        "python": ".".join(str(item) for item in sys.version_info[:3]),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "triton_windows": importlib.metadata.version("triton-windows"),
        "faster_version": importlib.metadata.version("faster-qwen3-tts"),
        "faster_module_bundle_sha256": _bundle_sha256(Path(faster.__file__).parent),
        "worker_source_bundle_sha256": _bundle_sha256(
            repo_root / "worker" / "src" / "qwen_tts_bridge_worker"
        ),
        "gpu_name": gpu.name if gpu else None,
        "gpu_capability": [gpu.major, gpu.minor] if gpu else None,
        "gpu_total_memory_bytes": gpu.total_memory if gpu else None,
    }


def _policy_path(profile_path: Path, profile: dict[str, object]) -> Path:
    value = profile.get("evidence_policy")
    if not isinstance(value, str) or not value:
        raise ValueError("profile lacks evidence_policy")
    path = Path(value)
    return path if path.is_absolute() else (profile_path.parent / path).resolve()


def _bundle_sha256(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*.py")):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _object(value: dict[str, object], name: str) -> dict[str, object]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise ValueError(f"policy lacks object {name}")
    return result


def _load_object(value: bytes, name: str) -> dict[str, object]:
    parsed = json.loads(value.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} is not an object")
    return parsed


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
