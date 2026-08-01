"""Seal a frequency-allowlist runtime policy from immutable benchmark evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-policy", type=Path, required=True)
    parser.add_argument("--holdout-run", type=Path, required=True)
    parser.add_argument("--same-wheel-summary", type=Path, required=True)
    parser.add_argument("--candidate-ab-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    policy = seal_policy(
        source_policy_path=args.source_policy,
        holdout_run_dir=args.holdout_run,
        same_wheel_summary_path=args.same_wheel_summary,
        candidate_ab_run_dir=args.candidate_ab_run,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"acceptance_pass": policy["acceptance_pass"], "output": str(args.output)}))
    return 0 if policy["acceptance_pass"] else 1


def seal_policy(
    *,
    source_policy_path: Path,
    holdout_run_dir: Path,
    same_wheel_summary_path: Path,
    candidate_ab_run_dir: Path,
) -> dict[str, object]:
    source_policy = _load_object(source_policy_path, "source policy")
    holdout_manifest_path = holdout_run_dir / "run-manifest.json"
    candidate_manifest_path = candidate_ab_run_dir / "run-manifest.json"
    holdout_manifest = _load_object(holdout_manifest_path, "holdout manifest")
    candidate_manifest = _load_object(candidate_manifest_path, "candidate A/B manifest")
    same_wheel_summary = _load_object(same_wheel_summary_path, "same-wheel summary")

    checks = _evidence_checks(
        source_policy,
        holdout_manifest,
        candidate_manifest,
        same_wheel_summary,
    )
    holdout_runtime = _mapping(holdout_manifest.get("runtime"))
    candidate_runtime = _mapping(candidate_manifest.get("runtime"))
    policy = {
        "runtime_policy_schema_version": 2,
        "policy_name": "rtx4090-frequency-exact-allowlist-r9-sealed",
        "status": "validated_research_configuration",
        "source_policy": _provenance(source_policy_path),
        "holdout": {
            "run_manifest": _provenance(holdout_manifest_path),
            "records": _provenance(holdout_run_dir / "records.jsonl"),
            "validation": _provenance(
                holdout_run_dir.parent / "holdout-validation.json"
            ),
            "corpus_id": holdout_manifest.get("corpus_id"),
            "corpus_split": holdout_manifest.get("corpus_split"),
            "input_sha256": holdout_manifest.get("input_sha256"),
            "profile": holdout_manifest.get("profile"),
            "seed": holdout_manifest.get("seed"),
            "seed_mode": holdout_manifest.get("seed_mode"),
        },
        "same_wheel_ab": {
            "summary": _provenance(same_wheel_summary_path),
            "candidate_run_manifest": _provenance(candidate_manifest_path),
        },
        "runtime_contract": {
            "worker_source_bundle_sha256": holdout_runtime.get("bridge_worker_source_bundle_sha256"),
            "faster_qwen3_tts_source": holdout_runtime.get("faster_qwen3_tts_source"),
            "torch_version": holdout_runtime.get("torch_version"),
            "cuda_version": holdout_runtime.get("cuda_version"),
            "python": holdout_runtime.get("python"),
            "platform": holdout_runtime.get("platform"),
            "triton_windows_version": holdout_runtime.get("triton_windows_version"),
            "flash_attention_available": holdout_runtime.get("flash_attention_available"),
            "candidate_ab_bridge_commit": candidate_runtime.get("bridge_commit"),
            "candidate_ab_bridge_tree": candidate_runtime.get("bridge_git_tree"),
            "holdout_bridge_commit": holdout_runtime.get("bridge_commit"),
            "holdout_bridge_tree": holdout_runtime.get("bridge_git_tree"),
            "runtime_agreement": {
                "worker_bundle": candidate_runtime.get("bridge_worker_source_bundle_sha256")
                == holdout_runtime.get("bridge_worker_source_bundle_sha256"),
                "faster_module_bundle": _nested(candidate_runtime, "faster_qwen3_tts_source", "module_bundle_sha256")
                == _nested(holdout_runtime, "faster_qwen3_tts_source", "module_bundle_sha256"),
                "faster_source_commit": _nested(candidate_runtime, "faster_qwen3_tts_source", "source_commit")
                == _nested(holdout_runtime, "faster_qwen3_tts_source", "source_commit"),
                "torch": candidate_runtime.get("torch_version") == holdout_runtime.get("torch_version"),
                "cuda": candidate_runtime.get("cuda_version") == holdout_runtime.get("cuda_version"),
                "triton": candidate_runtime.get("triton_windows_version")
                == holdout_runtime.get("triton_windows_version"),
            },
        },
        "installed_toolchain_provenance": {
            "python_executable": sys.executable,
            "triton_windows": _installed_distribution("triton-windows"),
            "torch": _installed_distribution("torch"),
        },
        "tool_provenance": {
            "policy_builder": _provenance(Path(__file__)),
            "corpus_runner": _provenance(_repo_root() / "scripts" / "qwen_corpus_discovery.py"),
            "corpus_validator": _provenance(
                _repo_root() / "scripts" / "validate_qwen_corpus_discovery.py"
            ),
            "route_report_builder": _provenance(
                _repo_root() / "scripts" / "qwen_holdout_route_report.py"
            ),
        },
        "acceptance_checks": checks,
    }
    policy["acceptance_pass"] = all(checks.values())
    return policy


def _evidence_checks(
    source_policy: Mapping[str, object],
    holdout: Mapping[str, object],
    candidate: Mapping[str, object],
    summary: Mapping[str, object],
) -> dict[str, bool]:
    holdout_runtime = _mapping(holdout.get("runtime"))
    candidate_runtime = _mapping(candidate.get("runtime"))
    agreement = {
        "worker_bundle": candidate_runtime.get("bridge_worker_source_bundle_sha256")
        == holdout_runtime.get("bridge_worker_source_bundle_sha256"),
        "faster_module_bundle": _nested(candidate_runtime, "faster_qwen3_tts_source", "module_bundle_sha256")
        == _nested(holdout_runtime, "faster_qwen3_tts_source", "module_bundle_sha256"),
        "torch": candidate_runtime.get("torch_version") == holdout_runtime.get("torch_version"),
        "cuda": candidate_runtime.get("cuda_version") == holdout_runtime.get("cuda_version"),
        "triton": candidate_runtime.get("triton_windows_version")
        == holdout_runtime.get("triton_windows_version"),
    }
    return {
        "source_policy_is_frozen": source_policy.get("status") == "frozen_for_one_measurement_holdout",
        "holdout_completed": holdout.get("status") == "completed",
        "holdout_is_measurement_split": holdout.get("corpus_split") == "runtime_measurement_holdout",
        "same_wheel_ab_passed": summary.get("passed") is True,
        "profile_sha_matches_source_policy": _nested(holdout, "profile", "sha256")
        == source_policy.get("profile_sha256"),
        "worker_bundle_matches_ab": agreement["worker_bundle"],
        "faster_module_bundle_matches_ab": agreement["faster_module_bundle"],
        "torch_matches_ab": agreement["torch"],
        "cuda_matches_ab": agreement["cuda"],
        "triton_matches_ab": agreement["triton"],
        "generation_prime_succeeded": _nested(holdout, "engine_warmup", "prefill_generation_prime_ready") is True,
    }


def _installed_distribution(name: str) -> dict[str, object]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return {"status": "unavailable", "distribution": name}
    files = sorted(distribution.files or (), key=lambda item: str(item).lower())
    digest = hashlib.sha256()
    present_files = 0
    for relative_path in files:
        path = Path(distribution.locate_file(relative_path))
        if not path.is_file():
            continue
        digest.update(str(relative_path).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        present_files += 1
    return {
        "status": "installed_distribution_bundle",
        "distribution": name,
        "metadata_name": distribution.metadata.get("Name"),
        "version": distribution.version,
        "file_count": present_files,
        "bundle_sha256": digest.hexdigest(),
        "original_wheel": "unavailable_in_local_pip_cache",
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _nested(value: Mapping[str, object], key: str, nested_key: str) -> object:
    nested = value.get(key)
    return nested.get(nested_key) if isinstance(nested, Mapping) else None


def _load_object(path: Path, name: str) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


def _provenance(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    raise SystemExit(main())
