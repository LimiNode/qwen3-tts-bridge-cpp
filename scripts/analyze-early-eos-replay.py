"""Read-only prefix-risk and causal startup-gate replay; not speech acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

SAMPLE = re.compile(r"step=(\d+) c0=(\d+) u=([0-9.eE+-]+) subseq=(\d+)$")
PREDICTOR = re.compile(r"step=(\d+) codes=([0-9,]+)$")
TRACE_LIMIT = 128
FRAME_BYTES = 1920 * 2  # The retained mono 24 kHz PCM16 / 12.5 Hz codec.


def finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("expected a finite nonnegative measurement")
    return number


def parse_traces(stderr: str) -> dict[int, dict[str, Any]]:
    """Associate serial engine traces with their request_finished identifier."""
    finished: dict[int, dict[str, Any]] = {}
    samples: dict[int, dict[str, Any]] = {}
    codes: dict[int, list[int]] = {}
    signal: dict[str, Any] | None = None
    for line in stderr.splitlines():
        if "[Sample] " in line:
            match = SAMPLE.fullmatch(line.split("[Sample] ", 1)[1])
            if not match:
                raise ValueError("malformed Talker sample trace")
            step, token, uniform, subseq = match.groups()
            index = int(step)
            draw = finite(uniform)
            if index != len(samples) or index >= TRACE_LIMIT or draw >= 1:
                raise ValueError("noncontiguous or invalid sample trace")
            if int(subseq) != index * 16:
                raise ValueError("unexpected predictor subsequence schedule")
            samples[index] = {"c0": int(token), "uniform": draw}
        elif "[ARTrace] predictor step=" in line:
            match = PREDICTOR.fullmatch(line.split("predictor ", 1)[1])
            if not match:
                raise ValueError("malformed predictor trace")
            step, values = match.groups()
            index = int(step)
            frame = [int(value) for value in values.split(",")]
            if index != len(codes) or len(frame) != 16:
                raise ValueError("noncontiguous or incomplete predictor frame")
            if index not in samples or frame[0] != samples[index]["c0"]:
                raise ValueError("Talker/predictor c0 mismatch")
            codes[index] = frame
        elif line.startswith("qtb_metric "):
            metric = json.loads(line[len("qtb_metric ") :])
            if metric.get("event") == "native_pcm_signal":
                if signal is not None or metric.get("chunk_index") != 0:
                    raise ValueError("overlapping or duplicate first PCM signal")
                for name in ("float_peak_abs", "float_rms", "s16_peak_abs", "s16_rms"):
                    finite(metric[name])
                signal = metric
            elif metric.get("event") == "request_finished":
                request_id = metric["request_id"]
                if request_id in finished or signal is None:
                    raise ValueError("duplicate terminal or missing first PCM signal")
                if signal["request_id"] != request_id:
                    raise ValueError("interleaved requests cannot be replayed")
                count = metric["qwen_n_frames"]
                eos = metric.get("execution_outcome") == "natural_eos"
                if list(codes) != list(range(min(count, TRACE_LIMIT))):
                    raise ValueError("missing predictor features")
                if list(samples) != list(range(min(count + int(eos), TRACE_LIMIT))):
                    raise ValueError("missing Talker features or EOS decision")
                finished[request_id] = {
                    "samples": list(samples.values())[:3],
                    "codes": list(codes.values())[:3],
                    "signal": signal,
                    "finished": metric,
                }
                samples, codes, signal = {}, {}, None
    if samples or codes or signal is not None:
        raise ValueError("unterminated engine trace")
    return finished


def duration_proxy(text: str, frames: int, outcome: str) -> bool | None:
    """Prespecified long-text duration anomaly, not a content/quality label."""
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    if len(words) < 6 or sum(map(len, words)) < 24 or outcome != "natural_eos":
        return None
    return frames <= 12


def fit_prefixes(rows: list[dict[str, Any]], horizon: int) -> list[list[int]]:
    """Freeze exact Talker prefixes from training positives only."""
    return [
        list(prefix)
        for prefix in sorted(
            {
                tuple(frame[0] for frame in row["codes"][:horizon])
                for row in rows
                if 0 <= row["seed"] <= 15
                and row["duration_proxy"] is True
                and len(row["codes"]) >= horizon
            }
        )
    ]


def prefix_risk(row: dict[str, Any], prefixes: list[list[int]], horizon: int) -> bool:
    # This decision deliberately cannot see the terminal label or total frames.
    observed = [frame[0] for frame in row["codes"][:horizon]]
    return len(observed) == horizon and observed in prefixes


def confusion(
    rows: list[dict[str, Any]], prefixes: list[list[int]], horizon: int
) -> dict[str, Any]:
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "unassessed": 0}
    for row in rows:
        label = row["duration_proxy"]
        if label is None or len(row["codes"]) < horizon:
            counts["unassessed"] += 1
            continue
        predicted = prefix_risk(row, prefixes, horizon)
        counts[("t" if predicted == label else "f") + ("p" if predicted else "n")] += 1
    result: dict[str, Any] = dict(counts)
    for name, numerator, denominator in (
        ("sensitivity", counts["tp"], counts["tp"] + counts["fn"]),
        ("specificity", counts["tn"], counts["tn"] + counts["fp"]),
        ("false_negative_rate", counts["fn"], counts["tp"] + counts["fn"]),
        ("false_positive_rate", counts["fp"], counts["tn"] + counts["fp"]),
    ):
        result[name] = numerator / denominator if denominator else None
    return result


def release_boundary(row: dict[str, Any], horizon: int) -> dict[str, Any]:
    """Replay actual callback granularity; >N frames proves frame N is not EOS."""
    gate = horizon if row["duration_proxy"] is not None else 0
    cumulative = 0
    release = None
    previous = -1.0
    for chunk in row["chunks"]:
        arrival = finite(chunk["arrival_ms"])
        byte_count = chunk["audio_bytes"]
        if arrival < previous or arrival > row["terminal_ms"]:
            raise ValueError("chunk/terminal ordering is inconsistent")
        if (
            not isinstance(byte_count, int)
            or byte_count <= 0
            or byte_count % FRAME_BYTES
        ):
            raise ValueError("chunk is not complete 24 kHz PCM16 codec frames")
        cumulative += byte_count // FRAME_BYTES
        if release is None and cumulative > gate:
            release = arrival
        previous = arrival
    if cumulative != row["frames"]:
        raise ValueError("PCM frame count disagrees with native terminal")
    return {
        "horizon": horizon,
        "gate_bypassed_unassessed_text": gate != horizon,
        "release_ms": release,
        "decision_ms": release if release is not None else row["terminal_ms"],
        "added_first_pcm_ms": release - row["first_pcm_ms"]
        if release is not None
        else None,
        "proxy_failure_pcm_exposed": row["duration_proxy"] is True
        and release is not None,
        "uncommitted_at_terminal": release is None,
    }


def quantiles(values: list[float]) -> dict[str, Any]:
    values = sorted(values)
    count = len(values)
    if not count:
        return {"n": 0, "p50": None, "p95": None}
    middle = count // 2
    median = values[middle] if count % 2 else (values[middle - 1] + values[middle]) / 2
    return {"n": count, "p50": median, "p95": values[math.ceil(0.95 * count) - 1]}


def analyze_run(run: Path) -> dict[str, Any]:
    names = ("requests.jsonl", "benchmark.json", "stderr.log", "invocation.json")
    if any((run / name).stat().st_size > 64 * 1024 * 1024 for name in names):
        raise ValueError("input exceeds the bounded study size")
    data = {name: (run / name).read_bytes() for name in names}
    requests = [
        json.loads(line) for line in data["requests.jsonl"].decode().splitlines()
    ]
    benchmark = json.loads(data["benchmark.json"])
    invocation = json.loads(data["invocation.json"])
    traces = parse_traces(data["stderr.log"].decode())
    if benchmark.get("warmups") or not 1 <= len(requests) <= 4096:
        raise ValueError("study requires 1..4096 serial requests and no hidden warmups")
    if len(requests) != len(benchmark["requests"]) or len(traces) != len(requests):
        raise ValueError("request/trace/benchmark count mismatch")
    seeds = [request["seed"] for request in requests]
    if len(set(seeds)) != len(seeds) or seeds != invocation["explicit_seed_order"]:
        raise ValueError("seed order is ambiguous or disagrees with invocation")
    if any(not isinstance(seed, int) or not 0 <= seed <= 31 for seed in seeds):
        raise ValueError("prespecified train/held-out seed ranges are 0..15 / 16..31")
    rows = []
    for index, (request, result) in enumerate(
        zip(requests, benchmark["requests"], strict=True)
    ):
        trace = traces.pop(result["request_id"])
        frames = result["completion_metadata"]["codec_frame_count"]
        if (
            request["label"] != result["label"]
            or frames != trace["finished"]["qwen_n_frames"]
        ):
            raise ValueError("request identity or frame count mismatch")
        if (
            result["completion_execution_outcome"]
            != trace["finished"]["execution_outcome"]
        ):
            raise ValueError("terminal outcome mismatch")
        row = {
            "request_id": result["request_id"],
            "seed": request["seed"],
            "text": request["text"],
            "text_utf8_sha256": hashlib.sha256(request["text"].encode()).hexdigest(),
            "frames": frames,
            "duration_proxy": duration_proxy(
                request["text"], frames, result["completion_execution_outcome"]
            ),
            "cold_first_request": index == 0,
            "first_pcm_ms": finite(result["first_audio_ms"]),
            "terminal_ms": finite(result["completed_ms"]),
            "chunks": result["chunks"],
            "samples": trace["samples"],
            "codes": trace["codes"],
            "first_pcm_signal": trace["signal"],
        }
        if not row["chunks"] or row["chunks"][0]["arrival_ms"] != row["first_pcm_ms"]:
            raise ValueError("first PCM timing does not match first chunk")
        row["policies"] = [
            release_boundary(row, horizon) for horizon in (0, 1, 2, 3, 12)
        ]
        rows.append(row)
    candidates = []
    for horizon in (1, 2, 3):
        prefixes = fit_prefixes(rows, horizon)
        candidates.append(
            {
                "horizon": horizon,
                "training_positive_prefixes": prefixes,
                "train": confusion(
                    [row for row in rows if row["seed"] <= 15], prefixes, horizon
                ),
                "held_out": confusion(
                    [row for row in rows if row["seed"] >= 16], prefixes, horizon
                ),
            }
        )
    policies = []
    for offset, horizon in enumerate((0, 1, 2, 3, 12)):
        observations = [row["policies"][offset] for row in rows]
        delays = [
            row["policies"][offset]["added_first_pcm_ms"]
            for row in rows
            if not row["cold_first_request"]
            and row["duration_proxy"] is False
            and row["policies"][offset]["release_ms"] is not None
        ]
        policies.append(
            {
                "horizon": horizon,
                "proxy_failures_pcm_exposed": sum(
                    item["proxy_failure_pcm_exposed"] for item in observations
                ),
                "uncommitted_at_terminal": sum(
                    item["uncommitted_at_terminal"] for item in observations
                ),
                "warm_non_short_added_first_pcm_ms": quantiles(delays),
            }
        )
    return {
        "scope": (
            "Same-text duration-proxy replay only; no speech-quality, cross-text, "
            "retry, live-gate or detector-overhead acceptance."
        ),
        "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_files": {
            name: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
            for name, value in data.items()
        },
        "invocation": invocation,
        "duration_proxy": {"max_frames": 12, "min_words": 6, "min_letters": 24},
        "split": {"training_seed_range": [0, 15], "held_out_seed_range": [16, 31]},
        "candidates": candidates,
        "policies": policies,
        "requests": rows,
        "limitations": [
            "No EOS logits in trace-only inputs",
            "PCM signal is a feature, not a silence-based label",
            "No held-out texts",
            "Natural EOS and a longer WAV do not prove spoken-text coverage",
            "No retry or physical playback was run; arrival-based boundaries "
            "are retrospective causal replay",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_run(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
