"""Compare two diagnostic raw s16le PCM captures without external dependencies."""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-rms-delta", type=float)
    parser.add_argument("--min-snr-db", type=float)
    parser.add_argument("--max-abs-delta", type=int)
    return parser.parse_args()


def read_metadata(capture: Path) -> dict[str, object]:
    metadata_path = capture.with_name(f"{capture.name}.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid PCM capture metadata: {metadata_path}") from exc
    if metadata.get("measurement") != "raw_s16le_pcm_capture":
        raise ValueError(f"unexpected PCM capture measurement: {metadata_path}")
    if metadata.get("completed") is not True:
        raise ValueError(f"PCM capture did not complete: {metadata_path}")
    if metadata.get("audio_format") != {
        "sample_format": "s16le",
        "sample_rate": 24_000,
        "channels": 1,
    }:
        raise ValueError(f"unsupported PCM capture format: {metadata_path}")
    if metadata.get("byte_count") != capture.stat().st_size:
        raise ValueError(f"PCM capture byte count disagrees with metadata: {capture}")
    return metadata


def read_samples(path: Path) -> tuple[bytes, array.array[int]]:
    raw = path.read_bytes()
    if len(raw) % 2 != 0:
        raise ValueError(f"s16le capture has an odd byte count: {path}")
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return raw, samples


def compute_metrics(expected: array.array[int], candidate: array.array[int]) -> dict[str, object]:
    if len(expected) != len(candidate):
        raise ValueError("PCM sample counts differ")
    exact_count = 0
    max_abs_delta = 0
    sum_abs_delta = 0
    sum_squared_delta = 0.0
    sum_squared_signal = 0.0
    for expected_sample, candidate_sample in zip(expected, candidate):
        delta = candidate_sample - expected_sample
        absolute_delta = abs(delta)
        if delta == 0:
            exact_count += 1
        max_abs_delta = max(max_abs_delta, absolute_delta)
        sum_abs_delta += absolute_delta
        sum_squared_delta += delta * delta
        sum_squared_signal += expected_sample * expected_sample
    sample_count = len(expected)
    rms_delta = math.sqrt(sum_squared_delta / sample_count)
    signal_rms = math.sqrt(sum_squared_signal / sample_count)
    snr_db = math.inf if rms_delta == 0 else 20.0 * math.log10(signal_rms / rms_delta)
    return {
        "sample_count": sample_count,
        "exact_sample_match_count": exact_count,
        "exact_sample_match_percent": 100.0 * exact_count / sample_count,
        "max_abs_pcm_delta": max_abs_delta,
        "mean_abs_pcm_delta": sum_abs_delta / sample_count,
        "rms_pcm_delta": rms_delta,
        "signal_rms_pcm": signal_rms,
        "snr_db": snr_db,
    }


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite parity report: {args.output}")
    expected_metadata = read_metadata(args.expected)
    candidate_metadata = read_metadata(args.candidate)
    expected_raw, expected_samples = read_samples(args.expected)
    candidate_raw, candidate_samples = read_samples(args.candidate)
    metadata_equal = expected_metadata == candidate_metadata
    byte_identical = expected_raw == candidate_raw
    metrics = compute_metrics(expected_samples, candidate_samples)
    thresholds = {
        "max_rms_delta": args.max_rms_delta,
        "min_snr_db": args.min_snr_db,
        "max_abs_delta": args.max_abs_delta,
    }
    threshold_pass = (
        (args.max_rms_delta is None or metrics["rms_pcm_delta"] <= args.max_rms_delta)
        and (args.min_snr_db is None or metrics["snr_db"] >= args.min_snr_db)
        and (args.max_abs_delta is None or metrics["max_abs_pcm_delta"] <= args.max_abs_delta)
    )
    result = {
        "schema_version": 1,
        "measurement": "cmp50hx_pcm_parity",
        "expected_path": str(args.expected),
        "candidate_path": str(args.candidate),
        "expected_sha256": hashlib.sha256(expected_raw).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate_raw).hexdigest(),
        "byte_identical": byte_identical,
        "metadata_equal": metadata_equal,
        "expected_metadata": expected_metadata,
        "candidate_metadata": candidate_metadata,
        "metrics": metrics,
        "thresholds": thresholds,
        "threshold_pass": threshold_pass,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"parity_report={args.output}")
    if not threshold_pass:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
