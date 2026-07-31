"""Fail closed on runtime acceptance for the 16..32-to-32 padding prototype."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping


_REQUIRED_SEMANTIC_CHECKS = (
    "runtime_padding_implementation",
    "attention_mask_parity",
    "position_id_parity",
    "rope_position_parity",
    "kv_cache_real_tokens_only",
    "first_step_logits_parity",
    "pad_tokens_absent_from_generation_state",
    "greedy_codec_trace_exact",
    "seeded_sampling_parity",
    "terminal_outcome_parity",
    "rng_neutrality",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-authorization", type=Path, required=True)
    parser.add_argument("--semantic-parity-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate(
        _load_object(args.research_authorization),
        _load_object(args.semantic_parity_report),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["runtime_acceptance_authorized"] else 1


def validate(
    research_authorization: Mapping[str, object],
    semantic_parity_report: Mapping[str, object],
) -> dict[str, object]:
    semantic_checks = semantic_parity_report.get("checks")
    checks = {
        "research_implementation_authorized": research_authorization.get(
            "research_implementation_authorized"
        )
        is True,
        "research_policy": research_authorization.get("approved_research_policy")
        == {
            "actual_minimum_length": 16,
            "actual_maximum_length": 32,
            "compiled_ceiling": 32,
            "compiled_graph_count": 1,
        },
        "semantic_report_checks": isinstance(semantic_checks, Mapping),
    }
    if isinstance(semantic_checks, Mapping):
        checks.update(
            {
                name: semantic_checks.get(name) is True
                for name in _REQUIRED_SEMANTIC_CHECKS
            }
        )
    else:
        checks.update({name: False for name in _REQUIRED_SEMANTIC_CHECKS})
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "qwen_padded_bucket_runtime_acceptance_schema_version": 1,
        "checks": checks,
        "failed_checks": failed,
        "runtime_acceptance_authorized": not failed,
        "holdout_authorized": not failed,
        "release_authorized": False,
        "decision": (
            "runtime_mechanism_may_proceed_to_holdout"
            if not failed
            else "do_not_run_holdout_or_release_padded_route"
        ),
    }


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
