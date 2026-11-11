"""Standalone prefill warmup, snapshot validation, and partial-reset operations."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, cast

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine.qwen.errors import QwenEngineError
from qwen_tts_bridge_worker.timing import elapsed_milliseconds, monotonic_seconds


def _load_prefill_allowlist_warmup_manifest(
    path: Path,
    lengths: tuple[int, ...],
) -> dict[int, dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QwenEngineError(
            f"failed to read prefill warmup manifest: {path}"
        ) from exc

    try:
        if text.lstrip().startswith("["):
            payload: Any = json.loads(text)
        elif text.lstrip().startswith("{"):
            payload = json.loads(text)
        else:
            payload = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise QwenEngineError(
            f"prefill warmup manifest is not valid JSON/JSONL: {path}"
        ) from exc

    default_speaker = ""
    rows: list[Any]
    if isinstance(payload, dict):
        rows_value = payload.get("rows")
        if not isinstance(rows_value, list):
            raise QwenEngineError("prefill warmup manifest dict must contain rows")
        default_speaker = str(payload.get("speaker") or "")
        rows = rows_value
    elif isinstance(payload, list):
        rows = payload
    else:
        raise QwenEngineError("prefill warmup manifest must be an object or list")

    needed = set(lengths)
    result: dict[int, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_length = row.get("talker_prefill_length")
        if raw_length is None:
            raw_length = row.get("prefill_shape_length")
        if raw_length is None:
            continue
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            continue
        if length not in needed or length in result:
            continue
        text_value = row.get("text")
        language = row.get("language", "Auto")
        if not isinstance(text_value, str) or not text_value:
            raise QwenEngineError(
                f"prefill warmup row for length {length} must contain text"
            )
        result[length] = {
            "text": text_value,
            "language": str(language or "Auto"),
            "speaker": str(row.get("speaker") or default_speaker),
            "instruction": str(row.get("instruction") or ""),
        }

    missing = [length for length in lengths if length not in result]
    if missing:
        raise QwenEngineError(
            f"prefill warmup manifest missing allowlisted lengths: {missing}"
        )
    return result


def _call_prefill_for_warmup(
    prefill_call: Any,
    talker: Any,
    tie: Any,
    tam: Any,
    tth: Any,
    tpe: Any,
    metadata: dict[str, Any],
    *,
    backend: str,
    mask_mode: str,
    config: QwenEngineConfig,
) -> tuple[Any, dict[str, object]]:
    torch = importlib.import_module("torch")
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    with torch.inference_mode():
        out, profile = prefill_call(
            talker,
            tie,
            tam,
            tth,
            tpe,
            prefill_backend=backend,
            prefill_mask_mode=mask_mode,
            prefill_compile_compat_mode=(
                "none" if backend == "eager" else config.prefill_compile_compat_mode
            ),
            prefill_compile_lengths=config.prefill_compile_lengths,
            prefill_compile_on_miss=config.prefill_compile_on_miss,
            prefill_unknown_shape_policy=config.prefill_unknown_shape_policy,
            input_metadata=metadata,
        )
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    return out, cast(dict[str, object], profile)


def _run_prefill_decode_state_warmup(
    model: Any,
    talker: Any,
    attention_mask: Any,
    prefill_out: Any,
    metadata: dict[str, Any],
) -> dict[str, object]:
    talker_graph = getattr(model, "talker_graph", None)
    if talker_graph is None:
        raise QwenEngineError("loaded faster model does not expose talker_graph")

    torch = importlib.import_module("torch")
    started_at = monotonic_seconds()
    with torch.inference_mode():
        prefill_kv_started = monotonic_seconds()
        prefill_len = int(talker_graph.prefill_kv(prefill_out.past_key_values))
        prefill_kv_ms = elapsed_milliseconds(prefill_kv_started)

        generation_state_started = monotonic_seconds()
        attention_mask_all_valid = (
            metadata.get("prefill_attention_mask_all_valid") is True
        )
        generation_attention_mask = None if attention_mask_all_valid else attention_mask
        talker_graph.set_generation_state(
            generation_attention_mask,
            getattr(talker, "rope_deltas", None),
            attention_mask_all_valid=attention_mask_all_valid,
        )
        generation_state_ms = elapsed_milliseconds(generation_state_started)

        replay_started = monotonic_seconds()
        if prefill_len >= int(talker_graph.max_seq_len) - 1:
            raise QwenEngineError(
                "prefill decode-state warmup length exceeds talker graph capacity: "
                f"prefill_len={prefill_len}, max_seq_len={talker_graph.max_seq_len}"
            )
        input_embeds = prefill_out.past_hidden[:, -1:, :]
        talker_graph.run(input_embeds, position=prefill_len)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        replay_ms = elapsed_milliseconds(replay_started)

        reset_started = monotonic_seconds()
        talker_graph.reset(prefill_len)
        reset_ms = elapsed_milliseconds(reset_started)

    profile = getattr(talker_graph, "last_generation_state_profile", None)
    profile_fields = dict(profile) if isinstance(profile, dict) else {}
    if profile_fields.get("generation_state_mask_cache_hit") is not True:
        raise QwenEngineError(
            "prefill decode-state warmup did not hit the generation mask cache: "
            f"{profile_fields}"
        )
    if profile_fields.get("generation_state_masks_built") != 0:
        raise QwenEngineError(
            f"prefill decode-state warmup rebuilt generation masks: {profile_fields}"
        )

    return {
        "prefill_decode_state_warmup": True,
        "prefill_decode_state_ready": True,
        "prefill_decode_state_length": prefill_len,
        "prefill_decode_state_warmup_duration_ms": elapsed_milliseconds(started_at),
        "prefill_decode_state_prefill_kv_ms": prefill_kv_ms,
        "prefill_decode_state_generation_state_ms": generation_state_ms,
        "prefill_decode_state_replay_ms": replay_ms,
        "prefill_decode_state_reset_ms": reset_ms,
        **{
            f"prefill_decode_state_{key}": value
            for key, value in profile_fields.items()
        },
    }


def _snapshot_prefill_output(out: Any) -> dict[str, Any]:
    return {
        "logits": _snapshot_value(getattr(out, "logits", None)),
        "past_hidden": _snapshot_value(getattr(out, "past_hidden", None)),
        "past_key_values": _snapshot_value(getattr(out, "past_key_values", None)),
    }


def _snapshot_value(value: Any) -> Any:
    if hasattr(value, "detach"):
        return value.detach().float().cpu().clone()
    if isinstance(value, tuple):
        return tuple(_snapshot_value(item) for item in value)
    if isinstance(value, list):
        return [_snapshot_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _snapshot_value(item) for key, item in value.items()}
    return value


def _prefill_snapshot_max_abs(left: Any, right: Any) -> float:
    if type(left) is not type(right):
        raise QwenEngineError(
            "prefill warmup output type mismatch: "
            f"{type(left).__name__} != {type(right).__name__}"
        )
    if hasattr(left, "shape") and hasattr(right, "shape"):
        if tuple(left.shape) != tuple(right.shape):
            raise QwenEngineError(
                "prefill warmup output shape mismatch: "
                f"{tuple(left.shape)} != {tuple(right.shape)}"
            )
        if getattr(left, "dtype", None) != getattr(right, "dtype", None):
            raise QwenEngineError(
                "prefill warmup output dtype mismatch: "
                f"{getattr(left, 'dtype', None)} != {getattr(right, 'dtype', None)}"
            )
        return float((left - right).abs().max().item()) if left.numel() else 0.0
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            raise QwenEngineError(
                "prefill warmup output dictionary keys mismatch: "
                f"{sorted(map(str, left))} != {sorted(map(str, right))}"
            )
        return max(
            (_prefill_snapshot_max_abs(left[key], right[key]) for key in left),
            default=0.0,
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            raise QwenEngineError(
                "prefill warmup output sequence length mismatch: "
                f"{len(left)} != {len(right)}"
            )
        return max(
            (
                _prefill_snapshot_max_abs(left_item, right_item)
                for left_item, right_item in zip(left, right, strict=True)
            ),
            default=0.0,
        )
    return 0.0


def _set_prefill_require_precompiled(model: Any, enabled: bool) -> None:
    if not hasattr(model, "prefill_require_precompiled"):
        raise QwenEngineError(
            "loaded faster model does not support prefill_require_precompiled; "
            "reinstall the bridge-patched faster-qwen3-tts wheel"
        )
    model.prefill_require_precompiled = bool(enabled)


def _profile_int(profile: dict[str, object], key: str) -> int:
    value = profile.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)
    return 0


def _warmup_pass_max_output_chunks(
    config: QwenEngineConfig,
    pass_index: int,
) -> int | None:
    if pass_index <= config.warmup_unbounded_passes:
        return None
    return config.warmup_max_output_chunks


def _reset_after_partial_generation(model: Any) -> dict[str, object]:
    reset = getattr(model, "reset_after_partial_generation", None)
    if not callable(reset):
        raise QwenEngineError(
            "loaded faster model does not expose reset_after_partial_generation()"
        )
    try:
        metadata = reset()
    except Exception as exc:
        raise QwenEngineError("failed to reset partial faster generation") from exc
    if not isinstance(metadata, dict):
        raise QwenEngineError("partial faster generation reset returned no metadata")
    if metadata.get("reset_api_version") != 1:
        raise QwenEngineError("partial faster generation reset API version mismatch")
    if metadata.get("talker_graph_reset") is not True:
        raise QwenEngineError("partial faster generation did not reset TalkerGraph")
    predictor_count = metadata.get("predictor_graphs_reset")
    if not isinstance(predictor_count, int) or predictor_count <= 0:
        raise QwenEngineError("partial faster generation did not reset PredictorGraph")
    for name in (
        "compiled_prefill_cache_preserved",
        "cuda_graphs_preserved",
        "generation_mask_cache_preserved",
    ):
        if metadata.get(name) is not True:
            raise QwenEngineError(
                f"partial faster generation reset did not preserve {name}"
            )
    return metadata
