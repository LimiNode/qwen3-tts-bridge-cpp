"""Run exact-allowlist semantic parity across prime and decode modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--eager-profile", type=Path, required=True)
    parser.add_argument("--compiled-profile", type=Path, required=True)
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--sampling-seed-count", type=int, default=5)
    parser.add_argument("--greedy-seed-count", type=int, default=3)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse complete child reports already present beside --output.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.sampling_seed_count <= 0 or args.greedy_seed_count <= 0:
        parser.error("seed counts must be positive")

    result = run_matrix(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"passed": result["passed"], "output": str(args.output)}))
    return 0 if result["passed"] else 1


def run_matrix(args: argparse.Namespace) -> dict[str, object]:
    eager_source = _load_object(args.eager_profile, "eager profile")
    compiled_source = _load_object(args.compiled_profile, "compiled profile")
    profile_dir = args.output.parent / f"{args.output.stem}-profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, object]] = []
    for do_sample, seed_count, decode_name in (
        (True, args.sampling_seed_count, "sampling"),
        (False, args.greedy_seed_count, "greedy"),
    ):
        for prime_enabled in (False, True):
            name = f"{decode_name}-prime-{'on' if prime_enabled else 'off'}"
            eager_path = profile_dir / f"{name}-eager.json"
            compiled_path = profile_dir / f"{name}-compiled.json"
            eager = dict(eager_source)
            compiled = dict(compiled_source)
            eager["do_sample"] = do_sample
            compiled["do_sample"] = do_sample
            eager["prefill_generation_prime"] = False
            compiled["prefill_generation_prime"] = prime_enabled
            _write_json(eager_path, eager)
            _write_json(compiled_path, compiled)
            report_path = args.output.parent / f"{args.output.stem}-{name}.json"
            command = [
                sys.executable,
                str(
                    Path(__file__).with_name(
                        "qwen_exact_allowlist_generation_parity.py"
                    )
                ),
                "--manifest",
                str(args.manifest),
                "--eager-profile",
                str(eager_path),
                "--compiled-profile",
                str(compiled_path),
                "--speaker",
                args.speaker,
                "--seed-start",
                str(args.seed_start),
                "--seed-count",
                str(seed_count),
                *(["--prime-generation"] if prime_enabled else []),
                "--output",
                str(report_path),
            ]
            resumed = (
                _resume_comparison(
                    args,
                    report_path,
                    eager_path,
                    compiled_path,
                )
                if args.resume
                else None
            )
            if resumed is not None:
                report = resumed
                returncode = 0 if report.get("passed") is True else 1
            else:
                completed = subprocess.run(command, check=False)
                report = _load_object(report_path, name)
                returncode = completed.returncode
            parity_pass = report.get("passed") is True
            executed = returncode in {0, 1}
            cases.append(
                {
                    "name": name,
                    "decode_mode": decode_name,
                    "prime_enabled": prime_enabled,
                    "seed_count": seed_count,
                    "eager_profile": _provenance(eager_path),
                    "compiled_profile": _provenance(compiled_path),
                    "report": _provenance(report_path),
                    "subprocess_returncode": returncode,
                    "parity_pass": parity_pass,
                    "executed": executed,
                    "passed": parity_pass if prime_enabled else executed,
                }
            )
    return {
        "artifact_schema_version": 1,
        "method": "eager_vs_exact_allowlist_generation_prime_semantic_matrix",
        "manifest": _provenance(args.manifest),
        "source_eager_profile": _provenance(args.eager_profile),
        "source_compiled_profile": _provenance(args.compiled_profile),
        "seed_start": args.seed_start,
        "cases": cases,
        "acceptance": {
            "prime_on_parity_pass": all(
                case["parity_pass"] for case in cases if case["prime_enabled"] is True
            ),
            "prime_off_completed": all(
                case["executed"] for case in cases if case["prime_enabled"] is False
            ),
            "prime_off_mismatch_observed": any(
                case["parity_pass"] is False
                for case in cases
                if case["prime_enabled"] is False
            ),
            "prime_off_observed": any(case["prime_enabled"] is False for case in cases),
            "prime_on_observed": any(case["prime_enabled"] is True for case in cases),
            "sampling_observed": any(
                case["decode_mode"] == "sampling" for case in cases
            ),
            "greedy_observed": any(case["decode_mode"] == "greedy" for case in cases),
        },
        "passed": (
            all(case["passed"] for case in cases)
            and any(
                case["parity_pass"] is False
                for case in cases
                if case["prime_enabled"] is False
            )
        ),
    }


def _load_object(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"cannot read {name}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _resume_comparison(
    args: argparse.Namespace,
    report_path: Path,
    eager_profile: Path,
    compiled_profile: Path,
) -> dict[str, Any] | None:
    if report_path.is_file():
        return _load_object(report_path, report_path.stem)

    eager_child_path = report_path.parent / f"{report_path.stem}-eager-runs.json"
    compiled_child_path = report_path.parent / f"{report_path.stem}-compiled-runs.json"
    if not eager_child_path.is_file() or not compiled_child_path.is_file():
        return None
    eager_child = _load_object(eager_child_path, eager_child_path.stem)
    compiled_child = _load_object(compiled_child_path, compiled_child_path.stem)
    eager_runs = eager_child.get("runs")
    compiled_runs = compiled_child.get("runs")
    if not isinstance(eager_runs, dict) or not isinstance(compiled_runs, dict):
        return None

    try:
        from qwen_exact_allowlist_generation_parity import (
            _candidate_rows,
            build_report,
        )
    except ModuleNotFoundError:  # Imported through the scripts package.
        from scripts.qwen_exact_allowlist_generation_parity import (
            _candidate_rows,
            build_report,
        )
    manifest = _load_object(args.manifest, "manifest")
    rows = _candidate_rows(manifest)
    seed_count = (
        args.sampling_seed_count
        if "sampling-" in report_path.stem
        else args.greedy_seed_count
    )
    report = build_report(
        manifest=args.manifest,
        eager_profile=eager_profile,
        compiled_profile=compiled_profile,
        rows=rows,
        seeds=list(range(args.seed_start, args.seed_start + seed_count)),
        eager=cast_runs(eager_runs),
        compiled=cast_runs(compiled_runs),
    )
    _write_json(report_path, report)
    return report


def cast_runs(value: dict[str, Any]) -> Mapping[str, list[dict[str, object]]]:
    return value


def _provenance(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__ == "__main__":
    raise SystemExit(main())
