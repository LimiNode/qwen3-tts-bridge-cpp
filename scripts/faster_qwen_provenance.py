"""Validation for immutable FasterQwen benchmark provenance manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_faster_qwen_provenance(path: Path) -> dict[str, object]:
    """Load a v1 manifest and verify that its referenced bundle is intact."""

    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid FasterQwen provenance manifest JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RuntimeError("unsupported FasterQwen provenance manifest schema")

    wheel_sha256 = _sha256_field(data, "wheel_sha256")
    bundle_sha256 = _sha256_field(data, "bundle_sha256")
    source_commit = _git_commit_field(data, "source_commit")
    bundle_path_value = data.get("bundle_path")
    if not isinstance(bundle_path_value, str) or not bundle_path_value:
        raise RuntimeError("FasterQwen provenance manifest is missing bundle_path")
    bundle_path = (path.parent / bundle_path_value).resolve()
    actual_bundle_sha256 = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if actual_bundle_sha256 != bundle_sha256:
        raise RuntimeError(
            "FasterQwen provenance bundle SHA-256 mismatch: "
            f"expected={bundle_sha256}, actual={actual_bundle_sha256}"
        )
    return {
        "schema_version": 1,
        "wheel_sha256": wheel_sha256,
        "source_commit": source_commit,
        "bundle_sha256": bundle_sha256,
        "bundle_path": str(bundle_path),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _sha256_field(data: dict[str, Any], name: str) -> str:
    value = str(data.get(name, "")).removeprefix("sha256=").lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RuntimeError(f"FasterQwen provenance manifest has invalid {name}")
    return value


def _git_commit_field(data: dict[str, Any], name: str) -> str:
    value = str(data.get(name, "")).lower()
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise RuntimeError(f"FasterQwen provenance manifest has invalid {name}")
    return value
