"""Publish a privacy-minimized summary of a Qwen operational soak report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_SCHEMA_VERSION = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.report.read_bytes()
    summary = _sanitize_report(_load_object(source))
    summary["source_report_sha256"] = _sha256(source)
    output = _json_bytes(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    return 0


def _sanitize_report(report: dict[str, object]) -> dict[str, object]:
    config = _object(report, "config")
    runtime = _object(report, "runtime")
    imports = _object(runtime, "imports")
    torch = _object(runtime, "torch")
    ready = _object(report, "ready")
    validation = _object(report, "validation")
    return {
        "qwen_operational_soak_summary_schema_version": _SCHEMA_VERSION,
        "acceptance_pass": report.get("acceptance_pass"),
        "config": {
            key: config[key]
            for key in (
                "requests",
                "cancellations_per_category",
                "expected_prefill_cache_entries",
                "operation_seed",
                "semantic_seed",
                "required_label",
                "expected_faster_source_bundle_sha256",
            )
            if key in config
        },
        "summary": _object(report, "summary"),
        "validation": validation,
        "ready": {
            key: ready[key]
            for key in ("capabilities", "warmed_up", "worker_version")
            if key in ready
        },
        "runtime": {
            "python": _runtime_python(runtime),
            "torch": {
                key: torch[key]
                for key in ("version", "cuda_runtime", "cuda_available")
                if key in torch
            },
            "faster_qwen3_tts": _runtime_import(imports, "faster_qwen3_tts"),
            "worker": _runtime_import(imports, "qwen_tts_bridge_worker"),
        },
        "excluded_fields": [
            "request_texts",
            "per_request_records",
            "absolute_paths",
            "process_ids",
            "session_ids",
            "host_identifiers",
            "raw_worker_metrics",
        ],
    }


def _runtime_python(runtime: dict[str, object]) -> str | None:
    python = runtime.get("python")
    if not isinstance(python, dict):
        return None
    version = python.get("version_info")
    if not isinstance(version, list) or not all(
        isinstance(item, int) for item in version
    ):
        return None
    return ".".join(str(item) for item in version)


def _runtime_import(
    imports: dict[str, object],
    name: str,
) -> dict[str, object]:
    value = imports.get(name)
    if not isinstance(value, dict):
        return {}
    source_git = value.get("source_git")
    result = {
        key: value[key]
        for key in ("available", "source_bundle_sha256")
        if key in value
    }
    distribution = value.get("distribution")
    if isinstance(distribution, dict) and distribution.get("version") is not None:
        result["version"] = distribution["version"]
    if isinstance(source_git, dict):
        result["source_commit"] = source_git.get("commit")
        result["source_git_dirty"] = source_git.get("dirty")
    return result


def _object(value: dict[str, object], name: str) -> dict[str, object]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise ValueError(f"report lacks object {name}")
    return result


def _load_object(value: bytes) -> dict[str, object]:
    parsed = json.loads(value.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("report is not an object")
    return parsed


def _json_bytes(value: dict[str, object]) -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
