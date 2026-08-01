"""Compare eager and exact-allowlist generation traces on fixed seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Mapping

try:
    from qwen_tail_case_matrix import _create_engine, _run_request
except ModuleNotFoundError:  # Imported through the scripts package.
    from scripts.qwen_tail_case_matrix import _create_engine, _run_request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--eager-profile", type=Path, required=True)
    parser.add_argument("--compiled-profile", type=Path, required=True)
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--seed-count", type=int, default=20)
    parser.add_argument("--prime-generation", action="store_true")
    parser.add_argument("--run-profile", choices=("eager", "compiled"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.seed_count <= 0:
        parser.error("--seed-count must be positive")

    if args.run_profile is not None:
        return _run_profile_child(args)
    return _run_comparison_parent(args)


def _run_comparison_parent(args: argparse.Namespace) -> int:
    manifest = _load_object(args.manifest, "manifest")
    rows = _candidate_rows(manifest)
    seeds = list(range(args.seed_start, args.seed_start + args.seed_count))
    eager = _run_profile_subprocess(args, "eager")
    compiled = _run_profile_subprocess(args, "compiled")
    report = build_report(
        manifest=args.manifest,
        eager_profile=args.eager_profile,
        compiled_profile=args.compiled_profile,
        rows=rows,
        seeds=seeds,
        eager=eager,
        compiled=compiled,
    )
    _write_report(args.output, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "passed": report["passed"],
                "row_count": len(rows),
                "seed_count": len(seeds),
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


def _run_profile_child(args: argparse.Namespace) -> int:
    assert args.run_profile is not None
    manifest = _load_object(args.manifest, "manifest")
    rows = _candidate_rows(manifest)
    seeds = list(range(args.seed_start, args.seed_start + args.seed_count))
    profile_path = (
        args.eager_profile if args.run_profile == "eager" else args.compiled_profile
    )
    profile = _load_object(profile_path, f"{args.run_profile} profile")
    progress: dict[str, object] = {
        "phase": "not_started",
        "record_id": None,
        "seed": None,
    }
    try:
        runs = _run_profile(
            profile,
            rows,
            args.speaker,
            seeds,
            args.run_profile,
            progress,
            bootstrap_seed=args.seed_start,
            prime_generation=args.prime_generation,
        )
        report: dict[str, object] = {
            "artifact_schema_version": 1,
            "phase": args.run_profile,
            "profile": _provenance(profile_path),
            "manifest": _provenance(args.manifest),
            "seed_start": seeds[0],
            "seed_count": len(seeds),
            "bootstrap_seed": args.seed_start,
            "generation_prime": args.prime_generation,
            "runs": runs,
            "passed": True,
        }
    except Exception as exc:
        report = {
            "artifact_schema_version": 1,
            "phase": args.run_profile,
            "profile": _provenance(profile_path),
            "manifest": _provenance(args.manifest),
            "seed_start": seeds[0],
            "seed_count": len(seeds),
            "failure": {
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "progress": progress,
            },
            "passed": False,
        }
    _write_report(args.output, report)
    return 0 if report["passed"] else 1


def _run_profile_subprocess(
    args: argparse.Namespace,
    phase: str,
) -> Mapping[str, list[dict[str, object]]]:
    output = args.output.parent / f"{args.output.stem}-{phase}-runs.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--manifest",
        str(args.manifest),
        "--eager-profile",
        str(args.eager_profile),
        "--compiled-profile",
        str(args.compiled_profile),
        "--speaker",
        args.speaker,
        "--seed-start",
        str(args.seed_start),
        "--seed-count",
        str(args.seed_count),
        *(["--prime-generation"] if args.prime_generation else []),
        "--run-profile",
        phase,
        "--output",
        str(output),
    ]
    completed = subprocess.run(command, check=False)
    if not output.exists():
        raise RuntimeError(f"{phase} subprocess failed without a report")
    child = _load_object(output, f"{phase} subprocess report")
    if completed.returncode != 0 or child.get("passed") is not True:
        raise RuntimeError(f"{phase} subprocess failed: {child.get('failure')}")
    runs = child.get("runs")
    if not isinstance(runs, dict):
        raise RuntimeError(f"{phase} subprocess report lacks runs")
    return runs


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_report(
    *,
    manifest: Path,
    eager_profile: Path,
    compiled_profile: Path,
    rows: list[dict[str, object]],
    seeds: list[int],
    eager: Mapping[str, list[dict[str, object]]],
    compiled: Mapping[str, list[dict[str, object]]],
) -> dict[str, object]:
    comparisons = []
    for row in rows:
        record_id = str(row["record_id"])
        comparisons.append(
            _compare_record(
                row,
                seeds,
                eager[record_id],
                compiled[record_id],
            )
        )
    return {
        "artifact_schema_version": 1,
        "method": "long_lived_fixed_seed_eager_vs_exact_allowlist_generation",
        "manifest": _provenance(manifest),
        "eager_profile": _provenance(eager_profile),
        "compiled_profile": _provenance(compiled_profile),
        "seed_start": seeds[0],
        "seed_count": len(seeds),
        "rows": comparisons,
        "passed": all(bool(row["passed"]) for row in comparisons),
    }


def _candidate_rows(manifest: Mapping[str, object]) -> list[dict[str, object]]:
    rows = manifest.get("rows")
    selected = manifest.get("selected_exact_lengths")
    if not isinstance(rows, list) or not isinstance(selected, list):
        raise ValueError("manifest lacks rows or selected_exact_lengths")
    expected = {int(length) for length in selected}
    by_length: dict[int, dict[str, object]] = {}
    for value in rows:
        if not isinstance(value, dict):
            raise ValueError("manifest row must be an object")
        record_id = value.get("record_id")
        text = value.get("text")
        length = value.get("talker_prefill_length")
        if (
            not isinstance(record_id, str)
            or not record_id
            or not isinstance(text, str)
            or not text
        ):
            raise ValueError("manifest row lacks record_id or text")
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise ValueError(f"manifest row {record_id} has invalid prefill length")
        if length not in expected or length in by_length:
            raise ValueError("manifest rows must contain one row per selected length")
        by_length[length] = dict(value)
    missing = expected - set(by_length)
    if missing:
        raise ValueError(
            f"manifest rows are missing selected lengths: {sorted(missing)}"
        )
    return [by_length[int(length)] for length in selected]


def _run_profile(
    profile: Mapping[str, object],
    rows: list[dict[str, object]],
    speaker: str,
    seeds: list[int],
    phase: str,
    progress: dict[str, object],
    *,
    bootstrap_seed: int,
    prime_generation: bool,
) -> dict[str, list[dict[str, object]]]:
    from qwen_tts_bridge_worker.engine.qwen_engine import _seed_runtime

    _seed_runtime(bootstrap_seed)
    engine = _create_engine(profile, speaker)
    try:
        engine.load()
        engine.warmup()
        if prime_generation and not bool(
            profile.get("prefill_generation_prime", False)
        ):
            progress.update(
                {
                    "phase": phase,
                    "record_id": "generation_prime",
                    "seed": bootstrap_seed - 1,
                }
            )
            _run_request(engine, rows[0], 0, speaker, bootstrap_seed - 1)
        result: dict[str, list[dict[str, object]]] = {}
        for request_id, row in enumerate(rows, 1):
            record_id = str(row["record_id"])
            result[record_id] = []
            for seed in seeds:
                progress.update({"phase": phase, "record_id": record_id, "seed": seed})
                result[record_id].append(
                    _run_request(engine, row, request_id, speaker, seed)
                )
        return result
    finally:
        engine.close()


def _compare_record(
    row: Mapping[str, object],
    seeds: list[int],
    eager_runs: list[Mapping[str, object]],
    compiled_runs: list[Mapping[str, object]],
) -> dict[str, object]:
    if len(eager_runs) != len(seeds) or len(compiled_runs) != len(seeds):
        raise ValueError("profile run count does not match the requested seed count")
    pairs = [
        _compare_seed(seed, eager_runs[index], compiled_runs[index])
        for index, seed in enumerate(seeds)
    ]
    return {
        "record_id": row["record_id"],
        "talker_prefill_length": row["talker_prefill_length"],
        "seed_pairs": pairs,
        "passed": all(bool(pair["passed"]) for pair in pairs),
    }


def _compare_seed(
    seed: int,
    eager: Mapping[str, object],
    compiled: Mapping[str, object],
) -> dict[str, object]:
    eager_route = _route(eager)
    compiled_route = _route(compiled)
    eager_trace = _trace(eager)
    compiled_trace = _trace(compiled)
    eager_sha = eager_trace.get("codec_sha256")
    compiled_sha = compiled_trace.get("codec_sha256")
    trace_equal = eager_trace == compiled_trace
    eager_route_ok = eager_route.get("prefill_backend_used") == "eager"
    compiled_route_ok = (
        compiled_route.get("prefill_backend_used") == "compile_reduce_overhead"
        and compiled_route.get("prefill_shape_policy") == "compiled_allowlist"
        and compiled_route.get("prefill_shape_allowlist_hit") is True
        and compiled_route.get("prefill_compile_cache_hit") is True
        and compiled_route.get("prefill_compile_fallback") is False
        and int(compiled_route.get("prefill_shape_call_ordinal", 0)) >= 3
    )
    terminal_equal = (
        eager.get("execution_outcome") == "completed"
        and compiled.get("execution_outcome") == "completed"
        and eager.get("generation_outcome") == "eos"
        and compiled.get("generation_outcome") == "eos"
    )
    return {
        "seed": seed,
        "eager_codec_sha256": eager_sha,
        "compiled_codec_sha256": compiled_sha,
        "codec_trace_exact": trace_equal,
        "terminal_eos_exact": terminal_equal,
        "eager_route_ok": eager_route_ok,
        "compiled_route_ok": compiled_route_ok,
        "passed": trace_equal
        and terminal_equal
        and eager_route_ok
        and compiled_route_ok,
    }


def _route(run: Mapping[str, object]) -> Mapping[str, object]:
    value = run.get("first_chunk_route")
    return value if isinstance(value, dict) else {}


def _trace(run: Mapping[str, object]) -> Mapping[str, object]:
    value = run.get("generation_trace")
    return value if isinstance(value, dict) else {}


def _load_object(path: Path, name: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {name}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _provenance(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__ == "__main__":
    raise SystemExit(main())
