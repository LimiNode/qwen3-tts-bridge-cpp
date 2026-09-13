#!/usr/bin/env python3
"""Validate sanitized CMP 50HX AR evidence against raw probe artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_map(
    evidence: dict[str, Any],
    field: str = "runs",
) -> dict[int, dict[str, Any]]:
    runs = evidence.get(field)
    if not isinstance(runs, list):
        raise ValueError(f"evidence.{field} must be an array")
    result: dict[int, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("seed"), int):
            raise ValueError("each evidence run must contain an integer seed")
        seed = run["seed"]
        if seed in result:
            raise ValueError(f"duplicate evidence seed: {seed}")
        result[seed] = run
    return result


def validate(
    probe_root: Path,
    evidence_path: Path,
    prior_evidence_path: Path,
) -> None:
    evidence = _load_json(evidence_path)
    prior = _load_json(prior_evidence_path)
    current_runs = _run_map(evidence)
    prior_runs = _run_map(prior, "post_fix_multi_seed_soak")

    missing_prior_seeds = set(current_runs) - set(prior_runs)
    if missing_prior_seeds:
        missing = sorted(missing_prior_seeds)
        raise ValueError(
            f"diagnostic seeds missing from prior evidence: {missing}"
        )

    step0 = evidence.get("first_divergence", {}).get("talker_step_0", {})
    expected_top5 = step0.get("top5")
    expected_draws = step0.get("philox_draw_by_seed")
    if not isinstance(expected_top5, list) or len(expected_top5) != 5:
        raise ValueError("step-0 sanitized top5 must have 5 entries")
    if not isinstance(expected_draws, dict):
        raise ValueError("step-0 sanitized Philox draws are required")
    observed_top5: tuple[tuple[int, float], ...] | None = None

    for seed, expected in current_runs.items():
        probe_path = probe_root / f"seed-{seed}" / "probe.json"
        wav_path = probe_root / f"seed-{seed}" / "output.wav"
        probe = _load_json(probe_path)
        metrics = probe.get("qtb_metrics")
        if not isinstance(metrics, list) or not metrics:
            raise ValueError(f"missing qtb_metrics: {probe_path}")
        terminal = probe.get("terminal")
        if not isinstance(terminal, dict):
            raise ValueError(f"missing terminal result: {probe_path}")

        trace = probe.get("ar_trace")
        if not isinstance(trace, list):
            raise ValueError(f"missing ar_trace: {probe_path}")
        step0_lines = [
            line for line in trace
            if isinstance(line, str) and line.startswith("sample step=0 ")
        ]
        if len(step0_lines) != 1:
            raise ValueError(f"expected one Talker step-0 line: {probe_path}")
        match = re.search(
            r"c0=(\d+) u=([^ ]+) selected_p=([^ ]+) .* top=([^ ]+)",
            step0_lines[0],
        )
        if match is None:
            raise ValueError(f"malformed Talker step-0 line: {probe_path}")
        draw = float(match.group(2))
        top5 = tuple(
            (int(item.split(":", 1)[0]), float(item.split(":", 1)[1]))
            for item in match.group(4).split(",")
        )
        if observed_top5 is None:
            observed_top5 = top5
        elif top5 != observed_top5:
            raise ValueError(f"seed {seed} step-0 top-5 differs across probes")
        expected_draw = expected_draws.get(str(seed))
        if expected_draw is None or abs(float(expected_draw) - draw) > 1e-9:
            raise ValueError(f"seed {seed} step-0 Philox draw mismatch")

        actual_hash = _sha256(wav_path)
        values = {
            "wav_sha256": actual_hash,
            "codec_frames": metrics[-1].get("qwen_n_frames"),
            "execution_outcome": terminal.get("execution_outcome"),
        }
        for field, actual in values.items():
            if expected.get(field) != actual:
                raise ValueError(
                    f"seed {seed} {field} mismatch: evidence={expected.get(field)!r} "
                    f"actual={actual!r}"
                )
            if prior_runs[seed].get(field) != actual:
                raise ValueError(
                    f"seed {seed} {field} differs from prior non-diagnostic evidence"
                )

    expected_top5_tuple = tuple(
        (int(item["token"]), float(item["probability"])) for item in expected_top5
    )
    if observed_top5 is None or any(
        token != expected_token or abs(probability - expected_probability) > 1e-6
        for (token, probability), (expected_token, expected_probability) in zip(
            observed_top5, expected_top5_tuple, strict=True
        )
    ):
        raise ValueError("step-0 top-5 does not match sanitized evidence")

    print(
        f"validated {len(current_runs)} seeds: raw WAV hashes, frame counts, "
        "outcomes, and prior soak parity"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--prior-evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate(args.probe_root, args.evidence, args.prior_evidence)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
