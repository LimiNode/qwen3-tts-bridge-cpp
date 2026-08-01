"""Fail closed on a completed Qwen corpus run and its exact route contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--runtime-split-audit", type=Path, required=True)
    parser.add_argument("--expected-corpus-id", required=True)
    parser.add_argument("--expected-speaker", required=True)
    parser.add_argument("--expected-seed", type=int, required=True)
    parser.add_argument("--expected-seed-mode", choices=("request_id", "fixed"), required=True)
    parser.add_argument("--expected-max-seq-len", type=int, required=True)
    parser.add_argument("--expected-max-audio-seconds", type=float, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-policy", type=Path)
    args = parser.parse_args()

    result = validate(
        input_path=args.input,
        audit_path=args.runtime_split_audit,
        expected_corpus_id=args.expected_corpus_id,
        expected_speaker=args.expected_speaker,
        expected_seed=args.expected_seed,
        expected_seed_mode=args.expected_seed_mode,
        expected_max_seq_len=args.expected_max_seq_len,
        expected_max_audio_seconds=args.expected_max_audio_seconds,
        profile_path=args.profile,
        run_dir=args.run_dir,
        holdout_policy_path=args.holdout_policy,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["overall_acceptance_pass"] else 1


def validate(
    *,
    input_path: Path,
    audit_path: Path,
    expected_corpus_id: str,
    expected_speaker: str,
    expected_seed: int,
    expected_seed_mode: str,
    expected_max_seq_len: int,
    expected_max_audio_seconds: float,
    profile_path: Path,
    run_dir: Path,
    holdout_policy_path: Path | None = None,
) -> dict[str, object]:
    records = _load_jsonl(input_path, "input")
    audit = _load_object(audit_path, "runtime split audit")
    profile = _load_object(profile_path, "profile")
    manifest = _load_object(run_dir / "run-manifest.json", "run manifest")
    rows = _load_jsonl(run_dir / "records.jsonl", "records")

    input_sha256 = _sha256(input_path)
    expected_ids = {str(record.get("record_id", "")) for record in records}
    observed_ids = [str(row.get("record_id", "")) for row in rows]
    observed_id_set = set(observed_ids)
    profile_sha256 = _sha256(profile_path)
    holdout_policy = (
        _load_object(holdout_policy_path, "holdout policy")
        if holdout_policy_path is not None
        else None
    )
    expected_split = (
        "runtime_measurement_holdout" if holdout_policy is not None else "discovery"
    )
    expected_audit_sha_key = (
        "holdout_sha256" if holdout_policy is not None else "discovery_sha256"
    )
    expected_audit_count_key = (
        "holdout_count" if holdout_policy is not None else "discovery_count"
    )

    provenance_checks = {
        "input_sha256": audit.get(expected_audit_sha_key) == input_sha256
        and manifest.get("input_sha256") == input_sha256,
        "corpus_id": audit.get("corpus_id") == expected_corpus_id
        and manifest.get("corpus_id") == expected_corpus_id,
        "corpus_split": manifest.get("corpus_split") == expected_split
        and all(record.get("corpus_split") == expected_split for record in records),
        "record_count": audit.get(expected_audit_count_key) == len(records),
        "profile_sha256": _nested_sha(manifest, "profile") == profile_sha256,
        "record_ids": bool(expected_ids)
        and "" not in expected_ids
        and observed_id_set == expected_ids
        and len(observed_ids) == len(observed_id_set),
        "manifest_status": manifest.get("status") == "completed",
        "seed_contract": manifest.get("seed") == expected_seed
        and manifest.get("seed_mode") == expected_seed_mode
        and manifest.get("speaker") == expected_speaker
        and manifest.get("selected_record_count") == len(records),
        "profile_limits": profile.get("max_seq_len") == expected_max_seq_len
        and profile.get("max_audio_seconds_per_utterance") == expected_max_audio_seconds,
        "profile_route_policy": profile.get("prefill_require_precompiled") is True
        and profile.get("prefill_compile_on_miss") is False,
        "runtime_provenance": _runtime_provenance_valid(manifest),
        "row_seed_contract": _row_seed_contract(
            rows,
            records,
            expected_seed,
            expected_seed_mode,
        ),
        "holdout_policy": _holdout_policy_valid(
            holdout_policy,
            holdout_policy_path,
            input_path,
            profile_path,
            profile,
            expected_corpus_id,
            expected_seed,
            expected_seed_mode,
            manifest,
        ),
    }

    execution_counts = Counter(_execution_outcome(row) for row in rows)
    generation_counts = Counter(_generation_outcome(row) for row in rows)
    route_failures = [
        {"record_id": row.get("record_id"), "failures": failures}
        for row in rows
        if (failures := _route_failures(row, profile, manifest))
    ]
    checks = {
        **provenance_checks,
        "all_rows_terminal": all(_execution_outcome(row) in {"completed", "failed", "cancelled"} for row in rows),
        "execution_completed": execution_counts == {"completed": len(rows)},
        "generation_eos": generation_counts == {"eos": len(rows)},
        "exact_route_contract": not route_failures,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "qwen_corpus_discovery_validation_schema_version": 2,
        "corpus_id": expected_corpus_id,
        "record_count": len(rows),
        "input_sha256": input_sha256,
        "records_sha256": _sha256(run_dir / "records.jsonl"),
        "profile_sha256": profile_sha256,
        "corpus_split": expected_split,
        "checks": checks,
        "failed_checks": failed_checks,
        "execution_outcomes": dict(sorted(execution_counts.items())),
        "generation_outcomes": dict(sorted(generation_counts.items())),
        "route_failure_count": len(route_failures),
        "route_failures": route_failures,
        "route_acceptance_pass": checks["exact_route_contract"],
        "generation_acceptance_pass": checks["generation_eos"],
        "overall_acceptance_pass": not failed_checks,
        "decision": "accepted_for_baseline" if not failed_checks else "not_a_valid_baseline",
    }


def _route_failures(
    row: Mapping[str, object],
    profile: Mapping[str, object],
    manifest: Mapping[str, object],
) -> list[str]:
    route = row.get("first_chunk_route")
    if not isinstance(route, Mapping):
        return ["missing_first_chunk_route"]
    length = route.get("talker_prefill_length")
    if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
        return ["invalid_talker_prefill_length"]
    allowlist = _positive_int_set(profile.get("prefill_compile_lengths"))
    cache_entries = profile.get("prefill_allowlist_max_entries")
    if not isinstance(cache_entries, int) or isinstance(cache_entries, bool) or cache_entries <= 0:
        return ["invalid_profile_cache_entries"]
    common = {
        "prefill_compile_on_miss": False,
        "prefill_require_precompiled": True,
        "prefill_dynamo_counter_available": True,
        "prefill_dynamo_unique_graphs_delta": 0,
        "prefill_compile_cache_entries": cache_entries,
        "prefill_compile_cache_entries_delta": 0,
        "prefill_compile_cache_evictions_delta": 0,
    }
    if length in allowlist:
        expected = {
            "prefill_shape_policy": "compiled_allowlist",
            "prefill_backend_used": "compile_reduce_overhead",
            "selected_chunk_schedule": profile.get("compiled_emit_chunk_schedule"),
            "chunk_schedule_decision": "compiled_allowlist",
            "prefill_compile_cache_hit": True,
            "prefill_shape_allowlist_hit": True,
            "prefill_compile_attempted": False,
            "prefill_compile_fallback": False,
            **common,
        }
    else:
        expected = {
            "prefill_shape_policy": "eager_unknown",
            "prefill_backend_used": "eager",
            "selected_chunk_schedule": profile.get("eager_emit_chunk_schedule"),
            "chunk_schedule_decision": "eager_unknown",
            "prefill_compile_cache_hit": False,
            "prefill_shape_allowlist_hit": False,
            "prefill_compile_attempted": False,
            "prefill_compile_fallback": False,
            **common,
        }
    failures = [field for field, value in expected.items() if route.get(field) != value]
    if length in allowlist:
        ordinal = route.get("prefill_shape_call_ordinal")
        warmup_ordinal = _warmup_ordinal(manifest, length)
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or warmup_ordinal is None
            or ordinal <= warmup_ordinal
        ):
            failures.append("prefill_shape_call_ordinal_after_warmup")
    return failures


def _warmup_ordinal(manifest: Mapping[str, object], length: int) -> int | None:
    engine_warmup = manifest.get("engine_warmup")
    if not isinstance(engine_warmup, Mapping):
        return None
    passes = engine_warmup.get("prefill_allowlist_warmup_passes")
    if not isinstance(passes, list):
        return None
    ordinals = [
        item.get("prefill_shape_call_ordinal")
        for item in passes
        if isinstance(item, Mapping)
        and item.get("talker_prefill_length") == length
        and isinstance(item.get("prefill_shape_call_ordinal"), int)
        and not isinstance(item.get("prefill_shape_call_ordinal"), bool)
    ]
    return max(ordinals) if ordinals else None


def _runtime_provenance_valid(manifest: Mapping[str, object]) -> bool:
    runtime = manifest.get("runtime")
    if not isinstance(runtime, Mapping):
        return False
    if not _nonempty_string(runtime.get("bridge_commit")):
        return False
    if not _nonempty_string(runtime.get("bridge_git_tree")):
        return False
    if runtime.get("bridge_tracked_tree_clean") is not True:
        return False
    if not _sha256_string(runtime.get("bridge_worker_source_bundle_sha256")):
        return False
    faster_source = runtime.get("faster_qwen3_tts_source")
    if not isinstance(faster_source, Mapping):
        return False
    if not _sha256_string(faster_source.get("module_bundle_sha256")):
        return False
    return (
        _nonempty_string(faster_source.get("source_commit"))
        and _nonempty_string(faster_source.get("source_git_tree"))
        and faster_source.get("source_tracked_tree_clean") is True
    )


def _holdout_policy_valid(
    policy: Mapping[str, object] | None,
    policy_path: Path | None,
    input_path: Path,
    profile_path: Path,
    profile: Mapping[str, object],
    expected_corpus_id: str,
    expected_seed: int,
    expected_seed_mode: str,
    manifest: Mapping[str, object],
) -> bool:
    if policy is None:
        return manifest.get("corpus_split") == "discovery"
    if policy_path is None:
        return False
    manifest_policy = manifest.get("holdout_policy")
    engine_warmup = manifest.get("engine_warmup")
    if not isinstance(manifest_policy, Mapping):
        return False
    if not isinstance(engine_warmup, Mapping):
        return False
    return (
        policy.get("status") == "frozen_for_one_measurement_holdout"
        and policy.get("corpus_id") == expected_corpus_id
        and policy.get("input_sha256") == _sha256(input_path)
        and policy.get("profile_sha256") == _sha256(profile_path)
        and policy.get("allow_padded_prefill") is False
        and policy.get("prefill_generation_prime") is True
        and profile.get("prefill_generation_prime") is True
        and engine_warmup.get("prefill_generation_prime") is True
        and engine_warmup.get("prefill_generation_prime_ready") is True
        and engine_warmup.get("prefill_generation_prime_requires_natural_eos") is True
        and policy.get("seed") == expected_seed
        and policy.get("seed_mode") == expected_seed_mode
        and manifest_policy.get("sha256") == _sha256(policy_path)
    )


def _row_seed_contract(
    rows: list[Mapping[str, object]],
    records: list[Mapping[str, object]],
    base_seed: int,
    seed_mode: str,
) -> bool:
    if seed_mode != "request_id":
        return False
    expected_request_ids = {
        str(record.get("record_id", "")): ordinal
        for ordinal, record in enumerate(records, 1)
    }
    for row in rows:
        record_id = row.get("record_id")
        if not isinstance(record_id, str):
            return False
        request_id = expected_request_ids.get(record_id)
        if request_id is None or row.get("request_id") != request_id:
            return False
        if row.get("derived_request_seed") != base_seed + request_id:
            return False
    return True


def _execution_outcome(row: Mapping[str, object]) -> str:
    value = row.get("execution_outcome")
    if isinstance(value, str):
        return value
    return "completed" if row.get("request_outcome") == "completed" else "unknown"


def _generation_outcome(row: Mapping[str, object]) -> str:
    value = row.get("generation_outcome")
    if isinstance(value, str):
        return value
    trace = row.get("generation_trace")
    if not isinstance(trace, Mapping):
        return "unknown"
    if trace.get("hit_eos") is True or trace.get("termination_reason") == "eos":
        return "eos"
    if trace.get("hit_max_new_tokens") is True or trace.get("termination_reason") == "max_new_tokens":
        return "max_new_tokens"
    if trace.get("hit_max_seq_len") is True or trace.get("termination_reason") == "max_seq_len":
        return "max_seq_len"
    return "unknown"


def _positive_int_set(value: object) -> set[int]:
    if not isinstance(value, list):
        return set()
    return {
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    }


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _sha256_string(value: object) -> bool:
    return _nonempty_string(value) and len(str(value)) == 64 and all(
        character in "0123456789abcdef" for character in str(value)
    )


def _load_jsonl(path: Path, name: str) -> list[dict[str, object]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{name} line {line_number} is not valid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"{name} line {line_number} must be an object")
        rows.append(value)
    if not rows:
        raise RuntimeError(f"{name} must not be empty")
    return rows


def _load_object(path: Path, name: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be an object")
    return value


def _nested_sha(value: Mapping[str, object], key: str) -> str | None:
    nested = value.get(key)
    return nested.get("sha256") if isinstance(nested, Mapping) else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
