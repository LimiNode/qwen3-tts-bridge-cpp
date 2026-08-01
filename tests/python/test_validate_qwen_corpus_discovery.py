from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "validate_qwen_corpus_discovery.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "validate_qwen_corpus_discovery",
    _SCRIPT_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class ValidateQwenCorpusDiscoveryTests(unittest.TestCase):
    def test_accepts_complete_seeded_provenance_and_route_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_valid_run(root)

            result = _MODULE.validate(**paths)

        self.assertTrue(result["overall_acceptance_pass"])

    def test_rejects_missing_row_seed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_valid_run(root)
            records_path = paths["run_dir"] / "records.jsonl"
            row = json.loads(records_path.read_text(encoding="utf-8"))
            row.pop("derived_request_seed")
            records_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

            result = _MODULE.validate(**paths)

        self.assertFalse(result["overall_acceptance_pass"])
        self.assertIn("row_seed_contract", result["failed_checks"])

    def test_accepts_frozen_holdout_with_generation_prime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_valid_run(root)
            _rewrite_as_frozen_holdout(paths)

            result = _MODULE.validate(**paths)

        self.assertTrue(result["overall_acceptance_pass"])
        self.assertEqual("runtime_measurement_holdout", result["corpus_split"])


def _write_valid_run(root: Path) -> dict[str, object]:
    input_path = root / "input.jsonl"
    input_record = {
        "record_id": "record-1",
        "text": "hello",
        "corpus_id": "corpus-v4",
        "corpus_split": "discovery",
    }
    input_path.write_text(json.dumps(input_record) + "\n", encoding="utf-8")
    input_sha256 = _sha256(input_path)
    audit_path = root / "audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "corpus_id": "corpus-v4",
                "discovery_sha256": input_sha256,
                "discovery_count": 1,
            }
        ),
        encoding="utf-8",
    )
    profile_path = root / "profile.json"
    profile = {
        "max_seq_len": 2048,
        "max_audio_seconds_per_utterance": 60.0,
        "prefill_require_precompiled": True,
        "prefill_compile_on_miss": False,
        "prefill_compile_lengths": [32],
        "prefill_allowlist_max_entries": 1,
        "compiled_emit_chunk_schedule": [8, 8, 12],
        "eager_emit_chunk_schedule": [8],
    }
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    run_dir = root / "run"
    run_dir.mkdir()
    manifest = {
        "status": "completed",
        "corpus_split": "discovery",
        "input_sha256": input_sha256,
        "corpus_id": "corpus-v4",
        "profile": {"sha256": _sha256(profile_path)},
        "speaker": "ryan",
        "seed": 20260731,
        "seed_mode": "request_id",
        "selected_record_count": 1,
        "runtime": {
            "bridge_commit": "a" * 40,
            "bridge_git_tree": "b" * 40,
            "bridge_tracked_tree_clean": True,
            "bridge_worker_source_bundle_sha256": "c" * 64,
            "faster_qwen3_tts_source": {
                "module_bundle_sha256": "d" * 64,
                "source_commit": "e" * 40,
                "source_git_tree": "f" * 40,
                "source_tracked_tree_clean": True,
            },
        },
        "engine_warmup": {
            "prefill_allowlist_warmup_passes": [
                {"talker_prefill_length": 32, "prefill_shape_call_ordinal": 0}
            ]
        },
    }
    (run_dir / "run-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    route = {
        "talker_prefill_length": 32,
        "prefill_shape_policy": "compiled_allowlist",
        "prefill_backend_used": "compile_reduce_overhead",
        "selected_chunk_schedule": [8, 8, 12],
        "chunk_schedule_decision": "compiled_allowlist",
        "prefill_compile_cache_hit": True,
        "prefill_shape_allowlist_hit": True,
        "prefill_compile_attempted": False,
        "prefill_compile_fallback": False,
        "prefill_compile_on_miss": False,
        "prefill_require_precompiled": True,
        "prefill_dynamo_counter_available": True,
        "prefill_dynamo_unique_graphs_delta": 0,
        "prefill_compile_cache_entries": 1,
        "prefill_compile_cache_entries_delta": 0,
        "prefill_compile_cache_evictions_delta": 0,
        "prefill_shape_call_ordinal": 1,
    }
    row = {
        "record_id": "record-1",
        "request_id": 1,
        "derived_request_seed": 20260732,
        "execution_outcome": "completed",
        "generation_outcome": "eos",
        "first_chunk_route": route,
    }
    (run_dir / "records.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return {
        "input_path": input_path,
        "audit_path": audit_path,
        "expected_corpus_id": "corpus-v4",
        "expected_speaker": "ryan",
        "expected_seed": 20260731,
        "expected_seed_mode": "request_id",
        "expected_max_seq_len": 2048,
        "expected_max_audio_seconds": 60.0,
        "profile_path": profile_path,
        "run_dir": run_dir,
    }


def _rewrite_as_frozen_holdout(paths: dict[str, object]) -> None:
    input_path = paths["input_path"]
    audit_path = paths["audit_path"]
    profile_path = paths["profile_path"]
    run_dir = paths["run_dir"]
    assert isinstance(input_path, Path)
    assert isinstance(audit_path, Path)
    assert isinstance(profile_path, Path)
    assert isinstance(run_dir, Path)

    record = json.loads(input_path.read_text(encoding="utf-8"))
    record["corpus_split"] = "runtime_measurement_holdout"
    input_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    input_sha256 = _sha256(input_path)
    audit_path.write_text(
        json.dumps(
            {
                "corpus_id": "corpus-v4",
                "holdout_sha256": input_sha256,
                "holdout_count": 1,
            }
        ),
        encoding="utf-8",
    )
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["prefill_generation_prime"] = True
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    policy_path = input_path.parent / "holdout-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "status": "frozen_for_one_measurement_holdout",
                "corpus_id": "corpus-v4",
                "input_sha256": input_sha256,
                "profile_sha256": _sha256(profile_path),
                "allow_padded_prefill": False,
                "prefill_generation_prime": True,
                "seed": 20260731,
                "seed_mode": "request_id",
            }
        ),
        encoding="utf-8",
    )
    manifest_path = run_dir / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["corpus_split"] = "runtime_measurement_holdout"
    manifest["input_sha256"] = input_sha256
    manifest["profile"] = {"sha256": _sha256(profile_path)}
    manifest["holdout_policy"] = {"sha256": _sha256(policy_path)}
    manifest["engine_warmup"].update(
        {
            "prefill_generation_prime": True,
            "prefill_generation_prime_ready": True,
            "prefill_generation_prime_requires_natural_eos": True,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    paths["holdout_policy_path"] = policy_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
