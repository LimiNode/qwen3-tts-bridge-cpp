"""Fail closed before launching a sealed internal FasterQwen profile."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

try:
    from model_runtime_manifest import verify_manifest
except ModuleNotFoundError:  # Imported as scripts.validate_internal_runtime_profile.
    from scripts.model_runtime_manifest import verify_manifest

try:
    from triton_installed_runtime_manifest import (
        verify_manifest as verify_triton_manifest,
    )
except ModuleNotFoundError:  # Imported as scripts.validate_internal_runtime_profile.
    from scripts.triton_installed_runtime_manifest import (
        verify_manifest as verify_triton_manifest,
    )

from qwen_tts_bridge_worker.cli import build_parser, build_worker_config
from qwen_tts_bridge_worker.config import QwenEngineConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-argument", action="append", default=[])
    args = parser.parse_args()

    profile_bytes = args.profile.read_bytes()
    profile = _load_object(profile_bytes, "profile")
    policy_path = _policy_path(args.profile, profile)
    policy = _load_object(policy_path.read_bytes(), "evidence policy")
    repo_root = args.profile.parents[1]
    effective_worker_config = _effective_worker_config(args.worker_argument)
    report = _validate(
        profile,
        policy,
        _runtime(repo_root),
        repo_root,
        model_path=args.model_path,
        effective_worker_config=effective_worker_config,
    )
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
    *,
    model_path: Path | None = None,
    effective_worker_config: dict[str, object] | None = None,
) -> dict[str, object]:
    failures: list[str] = []
    if profile.get("profile_status") != "internal_opt_in_only":
        failures.append("profile is not internal_opt_in_only")
    if policy.get("runtime_policy_schema_version") != 4:
        failures.append("runtime policy schema is unsupported")
    if policy.get("status") != "internal_opt_in_only":
        failures.append("runtime policy is not internal_opt_in_only")
    _compare("profile", profile, _object(policy, "profile_contract"), failures)
    _compare("runtime", runtime, _object(policy, "runtime_contract"), failures)
    _validate_effective_worker_config(
        effective_worker_config,
        _object(policy, "effective_worker_contract"),
        failures,
    )
    _validate_evidence(repo_root, _object(policy, "evidence_files"), failures)
    _validate_model_runtime_manifest(
        repo_root,
        profile,
        _object(policy, "model_runtime_manifest"),
        failures,
        model_path=model_path,
    )
    _validate_triton_installed_runtime_manifest(
        repo_root,
        _object(policy, "triton_installed_runtime_manifest"),
        failures,
    )
    return {"failures": failures, "runtime": runtime}


def _effective_worker_config(arguments: list[str]) -> dict[str, object] | None:
    if not arguments:
        return None
    if arguments[:2] != ["-m", "qwen_tts_bridge_worker"]:
        raise ValueError(
            "worker arguments must start with the worker module entry point"
        )
    parsed = build_parser().parse_args(arguments[2:])
    worker = build_worker_config(parsed)
    if not isinstance(worker.engine, QwenEngineConfig):
        raise ValueError("internal runtime profile must select the qwen engine")
    config = asdict(worker.engine)
    config.pop("kind", None)
    # The selected path is verified against the model content manifest separately.
    config.pop("model_path", None)
    return _json_compatible(config)


def _validate_effective_worker_config(
    actual: dict[str, object] | None,
    expected: dict[str, object],
    failures: list[str],
) -> None:
    if not expected:
        failures.append("effective worker configuration contract is missing")
        return
    if actual is None:
        failures.append("effective worker configuration was not supplied")
        return
    _compare("effective_worker", actual, expected, failures)


def _compare(
    label: str,
    actual: dict[str, object],
    expected: dict[str, object],
    failures: list[str],
) -> None:
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            failures.append(f"{label}.{key} does not match policy")


def _json_compatible(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    return value


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


def _validate_model_runtime_manifest(
    repo_root: Path,
    profile: dict[str, object],
    contract: dict[str, object],
    failures: list[str],
    *,
    model_path: Path | None,
) -> None:
    manifest_path = _contract_path(repo_root, contract.get("path"))
    expected_sha256 = contract.get("sha256")
    if manifest_path is None or not isinstance(expected_sha256, str):
        failures.append("model runtime manifest contract is invalid")
        return
    if not manifest_path.is_file():
        failures.append("model runtime manifest is missing")
        return
    if _sha256(manifest_path.read_bytes()) != expected_sha256:
        failures.append("model runtime manifest SHA does not match policy")
        return
    selected_model_path = model_path or _contract_path(
        repo_root, profile.get("model_path")
    )
    if selected_model_path is None:
        failures.append("profile model_path is invalid")
        return
    try:
        manifest = _load_object(manifest_path.read_bytes(), "model runtime manifest")
        verify_manifest(selected_model_path, manifest)
    except ValueError as exc:
        failures.append(f"model runtime manifest verification failed: {exc}")


def _validate_triton_installed_runtime_manifest(
    repo_root: Path,
    contract: dict[str, object],
    failures: list[str],
) -> None:
    manifest_path = _contract_path(repo_root, contract.get("path"))
    expected_sha256 = contract.get("sha256")
    distribution = contract.get("distribution")
    if (
        manifest_path is None
        or not isinstance(expected_sha256, str)
        or not isinstance(distribution, str)
        or not distribution
    ):
        failures.append("Triton installed runtime manifest contract is invalid")
        return
    if not manifest_path.is_file():
        failures.append("Triton installed runtime manifest is missing")
        return
    if _sha256(manifest_path.read_bytes()) != expected_sha256:
        failures.append("Triton installed runtime manifest SHA does not match policy")
        return
    try:
        manifest = _load_object(
            manifest_path.read_bytes(), "Triton installed runtime manifest"
        )
        verify_triton_manifest(distribution, manifest)
    except ValueError as exc:
        failures.append(f"Triton installed runtime verification failed: {exc}")


def _contract_path(repo_root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _runtime(repo_root: Path) -> dict[str, object]:
    torch = importlib.import_module("torch")
    faster = importlib.import_module("faster_qwen3_tts")
    gpu = torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None
    faster_directory = Path(faster.__file__).parent
    return {
        "python": ".".join(str(item) for item in sys.version_info[:3]),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "triton_windows": importlib.metadata.version("triton-windows"),
        "triton_windows_record_sha256": _distribution_record_sha256("triton-windows"),
        "faster_version": importlib.metadata.version("faster-qwen3-tts"),
        "faster_module_bundle_sha256": _bundle_sha256(faster_directory),
        **_git_provenance(faster_directory),
        "worker_source_bundle_sha256": _bundle_sha256(
            repo_root / "worker" / "src" / "qwen_tts_bridge_worker"
        ),
        "nvidia_driver_version": _nvidia_driver_version(),
        "gpu_name": gpu.name if gpu else None,
        "gpu_capability": [gpu.major, gpu.minor] if gpu else None,
        "gpu_total_memory_bytes": gpu.total_memory if gpu else None,
    }


def _distribution_record_sha256(distribution_name: str) -> str | None:
    record = importlib.metadata.distribution(distribution_name).read_text("RECORD")
    return _sha256(record.encode("utf-8")) if record is not None else None


def _git_provenance(path: Path) -> dict[str, object]:
    root = _git_output(path, "rev-parse", "--show-toplevel")
    if root is None:
        return {
            "faster_source_git_commit": None,
            "faster_source_git_tree": None,
            "faster_source_git_dirty": None,
            "faster_source_repository": None,
        }
    source_root = Path(root)
    status = _git_output(source_root, "status", "--porcelain", "--untracked-files=all")
    return {
        "faster_source_git_commit": _git_output(source_root, "rev-parse", "HEAD"),
        "faster_source_git_tree": _git_output(source_root, "rev-parse", "HEAD^{tree}"),
        "faster_source_git_dirty": bool(status) if status is not None else None,
        "faster_source_repository": _git_output(
            source_root, "remote", "get-url", "fork"
        ),
    }


def _git_output(path: Path, *arguments: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), *arguments],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _nvidia_driver_version() -> str | None:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    values = [line.strip() for line in output.splitlines() if line.strip()]
    return values[0] if len(values) == 1 else None


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
