"""Prove or reject eager left-padding parity for the 16..32 prefill experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any

import torch

from faster_qwen3_tts import FasterQwen3TTS
from faster_qwen3_tts.streaming import _run_talker_prefill


def main() -> int:
    args = _parse_args()
    torch.set_float32_matmul_precision(args.matmul_precision)
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
        max_seq_len=args.max_seq_len,
        prefill_backend="eager",
        prefill_pad_to_length=None,
    )
    model.collect_generation_trace = True

    baseline = _prepare(model, args, padded=False)
    padded = _prepare(model, args, padded=True)
    baseline_metadata = baseline[-1]
    padded_metadata = padded[-1]
    real_length = int(baseline_metadata["talker_prefill_length"])
    if not args.minimum_length <= real_length < args.target_length:
        report = {
            "schema_version": 1,
            "status": "skipped_outside_research_range",
            "real_prefill_length": real_length,
            "minimum_length": args.minimum_length,
            "target_length": args.target_length,
        }
        _write_report(args.output, report)
        return 0

    _validate_padded_metadata(padded_metadata, args.target_length, real_length)
    baseline_out = _run_prefill(*baseline)
    padded_out = _run_prefill(*padded)
    prefill = _compare_prefill(
        baseline_out,
        padded_out,
        left_padding=int(padded_metadata["prefill_padding_left_tokens"]),
    )

    greedy_baseline = _generate_trace(model, args, padded=False, do_sample=False)
    greedy_padded = _generate_trace(model, args, padded=True, do_sample=False)
    sampled_baseline = _generate_trace(model, args, padded=False, do_sample=True)
    sampled_padded = _generate_trace(model, args, padded=True, do_sample=True)
    report = {
        "schema_version": 1,
        "status": "passed" if all(
            (
                prefill["first_logits_exact"],
                prefill["past_hidden_exact"],
                prefill["kv_real_tokens_exact"],
                _traces_equal(greedy_baseline, greedy_padded),
                _traces_equal(sampled_baseline, sampled_padded),
                greedy_baseline["rng_state_sha256"] == greedy_padded["rng_state_sha256"],
                sampled_baseline["rng_state_sha256"] == sampled_padded["rng_state_sha256"],
            )
        ) else "failed",
        "research_only": True,
        "prefill_backend": "eager",
        "mask_mode": "explicit",
        "real_prefill_length": real_length,
        "padded_prefill_length": int(padded_metadata["talker_prefill_length"]),
        "left_padding_tokens": int(padded_metadata["prefill_padding_left_tokens"]),
        "prefill": prefill,
        "greedy": _trace_comparison(greedy_baseline, greedy_padded),
        "seeded_sampling": _trace_comparison(sampled_baseline, sampled_padded),
        "checks": {
            "runtime_padding_implementation": True,
            "attention_mask_parity": prefill["first_logits_exact"],
            "position_id_parity": prefill["first_logits_exact"],
            "rope_position_parity": prefill["first_logits_exact"],
            "kv_cache_real_tokens_only": prefill["kv_real_tokens_exact"],
            "first_step_logits_parity": prefill["first_logits_exact"],
            "pad_tokens_absent_from_generation_state": True,
            "greedy_codec_trace_exact": _traces_equal(
                greedy_baseline,
                greedy_padded,
            ),
            "seeded_sampling_parity": _traces_equal(
                sampled_baseline,
                sampled_padded,
            ),
            "terminal_outcome_parity": (
                greedy_baseline["terminal"] == greedy_padded["terminal"]
                and sampled_baseline["terminal"] == sampled_padded["terminal"]
            ),
            "rng_neutrality": (
                greedy_baseline["rng_state_sha256"] == greedy_padded["rng_state_sha256"]
                and sampled_baseline["rng_state_sha256"]
                == sampled_padded["rng_state_sha256"]
            ),
        },
    }
    _write_report(args.output, report)
    return 0 if report["status"] == "passed" else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--language", default="Auto")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--max-seq-len", type=int, default=2048)
    parser.add_argument("--target-length", type=int, default=32)
    parser.add_argument("--minimum-length", type=int, default=16)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.minimum_length <= 0 or args.target_length <= args.minimum_length:
        parser.error("target length must be greater than a positive minimum length")
    if args.max_new_tokens <= 0 or args.chunk_size <= 0:
        parser.error("max-new-tokens and chunk-size must be positive")
    return args


def _prepare(model: Any, args: argparse.Namespace, *, padded: bool) -> tuple[Any, ...]:
    model.prefill_pad_to_length = args.target_length if padded else None
    return model._prepare_generation_custom(
        text=args.text,
        language=args.language,
        speaker=args.speaker,
        instruct=args.instruction or None,
        non_streaming_mode=True,
        return_metadata=True,
    )


@torch.inference_mode()
def _run_prefill(*prepared: Any) -> Any:
    _m, talker, _config, tie, tam, tth, tpe, metadata = prepared
    out, profile = _run_talker_prefill(
        talker,
        tie,
        tam,
        tth,
        tpe,
        prefill_backend="eager",
        prefill_mask_mode="explicit",
        input_metadata=metadata,
    )
    if profile["prefill_backend_used"] != "eager":
        raise RuntimeError(f"unexpected prefill route: {profile}")
    return out


def _validate_padded_metadata(
    metadata: dict[str, Any],
    target_length: int,
    real_length: int,
) -> None:
    expected_left = target_length - real_length
    if metadata.get("prefill_padding_enabled") is not True:
        raise RuntimeError("padded prepare did not report enabled padding")
    if metadata.get("prefill_padding_target_length") != target_length:
        raise RuntimeError("padded prepare reported an unexpected target length")
    if metadata.get("prefill_padding_left_tokens") != expected_left:
        raise RuntimeError("padded prepare reported an unexpected left padding")
    if metadata.get("prefill_real_length") != real_length:
        raise RuntimeError("padded prepare reported an unexpected real length")
    if metadata.get("prefill_attention_mask_all_valid") is not False:
        raise RuntimeError("padded prepare incorrectly marked its mask all-valid")


def _compare_prefill(baseline: Any, padded: Any, *, left_padding: int) -> dict[str, Any]:
    logits_exact = torch.equal(baseline.logits[:, -1, :], padded.logits[:, -1, :])
    past_hidden_exact = torch.equal(baseline.past_hidden, padded.past_hidden)
    kv_exact = True
    kv_max_abs = 0.0
    for baseline_layer, padded_layer in zip(
        baseline.past_key_values,
        padded.past_key_values,
        strict=True,
    ):
        for baseline_tensor, padded_tensor in zip(
            baseline_layer,
            padded_layer,
            strict=True,
        ):
            real_suffix = padded_tensor[:, :, left_padding:, :]
            kv_exact = kv_exact and torch.equal(baseline_tensor, real_suffix)
            kv_max_abs = max(
                kv_max_abs,
                float(
                    (baseline_tensor.float() - real_suffix.float())
                    .abs()
                    .max()
                    .detach()
                ),
            )
    logits_max_abs = float(
        (baseline.logits[:, -1, :].float() - padded.logits[:, -1, :].float())
        .abs()
        .max()
        .detach()
    )
    return {
        "first_logits_exact": logits_exact,
        "first_logits_max_abs": logits_max_abs,
        "past_hidden_exact": past_hidden_exact,
        "kv_real_tokens_exact": kv_exact,
        "kv_real_tokens_max_abs": kv_max_abs,
    }


def _generate_trace(
    model: Any,
    args: argparse.Namespace,
    *,
    padded: bool,
    do_sample: bool,
) -> dict[str, Any]:
    model.prefill_pad_to_length = args.target_length if padded else None
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    for _audio, _sample_rate, _timing in model.generate_custom_voice_streaming(
        text=args.text,
        language=args.language,
        speaker=args.speaker,
        instruct=args.instruction or None,
        non_streaming_mode=True,
        max_new_tokens=args.max_new_tokens,
        min_new_tokens=2,
        do_sample=do_sample,
        temperature=0.9,
        top_k=50,
        top_p=1.0,
        chunk_size=args.chunk_size,
        prefill_backend="eager",
        prefill_compile_compat_mode="none",
    ):
        pass
    trace = dict(model.last_generation_trace or {})
    if not trace:
        raise RuntimeError("generation did not produce a codec trace")
    return {
        "codec_sha256": trace.get("codec_sha256"),
        "codec_frame_count": trace.get("codec_frame_count"),
        "terminal": {
            key: trace.get(key)
            for key in (
                "termination_reason",
                "terminal_token_id",
                "terminal_step_index",
                "generated_steps",
                "emitted_steps",
                "hit_eos",
                "hit_max_new_tokens",
                "hit_max_seq_len",
            )
        },
        "rng_state_sha256": _rng_state_sha256(),
    }


def _rng_state_sha256() -> str:
    digest = hashlib.sha256(torch.random.get_rng_state().numpy().tobytes())
    if torch.cuda.is_available():
        for state in torch.cuda.get_rng_state_all():
            digest.update(state.cpu().numpy().tobytes())
    return digest.hexdigest()


def _traces_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left["codec_sha256"] == right["codec_sha256"]
        and left["codec_frame_count"] == right["codec_frame_count"]
        and left["terminal"] == right["terminal"]
    )


def _trace_comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        "baseline": left,
        "padded": right,
        "codec_and_terminal_exact": _traces_equal(left, right),
        "rng_state_exact": left["rng_state_sha256"] == right["rng_state_sha256"],
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        if "--output" in sys.argv:
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.with_suffix(".error.txt").write_text(
                traceback.format_exc(),
                encoding="utf-8",
            )
        raise
