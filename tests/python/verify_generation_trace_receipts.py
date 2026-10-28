"""Verify C++ result receipts against controlled worker completion traces."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-wav", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--worker", required=True, type=Path)
    return parser.parse_args()


def run_case(
    args: argparse.Namespace,
    root: Path,
    mode: str,
    *,
    strict: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object] | None]:
    wav = root / f"{mode}-{'strict' if strict else 'diagnostic'}.wav"
    receipt = wav.with_suffix(".json")
    command = [
        str(args.save_wav),
        "--worker",
        str(args.python),
        "--worker-arg",
        str(args.worker),
        "--worker-arg",
        mode,
        "--output",
        str(wav),
        "--result-json",
        str(receipt),
        "--text",
        "Controlled generation trace",
        "--request-timeout-ms",
        "10000",
    ]
    if strict:
        command.append("--require-natural-eos")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(args.worker.parents[2] / "worker" / "src")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    value = (
        json.loads(receipt.read_text(encoding="utf-8"))
        if receipt.exists()
        else None
    )
    return completed, value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def require_receipt(
    value: dict[str, object] | None, message: str
) -> dict[str, object]:
    if value is None:
        raise RuntimeError(message)
    return value


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="qtb-generation-trace-") as temporary:
        root = Path(temporary)

        eos_run, eos = run_case(args, root, "eos", strict=True)
        require(eos_run.returncode == 0, eos_run.stdout + eos_run.stderr)
        eos = require_receipt(eos, "strict EOS run did not write a receipt")
        require(eos["generation_trace_available"] is True, "EOS trace was hidden")
        require(eos["termination_reason"] == "eos", "EOS reason changed")
        require(eos["hit_eos"] is True, "EOS flag changed")

        absent_run, absent = run_case(args, root, "absent")
        require(absent_run.returncode == 0, absent_run.stdout + absent_run.stderr)
        absent = require_receipt(absent, "missing-trace run did not write a receipt")
        require(
            absent["generation_trace_available"] is False,
            "missing trace was reported as available",
        )
        require(absent["termination_reason"] == "", "missing trace invented a reason")

        for mode, flag in (
            ("max_new_tokens", "hit_max_new_tokens"),
            ("max_seq_len", "hit_max_seq_len"),
            ("other", None),
        ):
            completed, receipt = run_case(args, root, mode)
            require(completed.returncode == 0, completed.stdout + completed.stderr)
            receipt = require_receipt(receipt, f"{mode} run did not write a receipt")
            require(
                receipt["generation_trace_available"] is True,
                f"{mode} trace was hidden",
            )
            require(receipt["termination_reason"] == mode, f"{mode} reason changed")
            if flag is not None:
                require(receipt[flag] is True, f"{mode} limit flag was lost")

        strict_absent, _ = run_case(args, root, "absent", strict=True)
        require(strict_absent.returncode != 0, "strict mode accepted missing trace")
        strict_max_tokens, _ = run_case(args, root, "max_new_tokens", strict=True)
        require(strict_max_tokens.returncode != 0, "strict mode accepted token limit")
        strict_max_seq, _ = run_case(args, root, "max_seq_len", strict=True)
        require(strict_max_seq.returncode != 0, "strict mode accepted sequence limit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
