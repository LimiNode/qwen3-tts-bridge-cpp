"""Streaming chunk timing and optional CUDA stall telemetry."""

from __future__ import annotations

import importlib
import os
from typing import Any


def _first_chunk_timing_fields(
    chunk_timing: dict[str, object],
    *,
    next_wall_ms: float,
    pcm_convert_ms: float,
    stream_next_gpu_ms: float | None = None,
    stream_next_gpu_ready: bool | None = None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "next_wall_ms": next_wall_ms,
        "pcm_convert_ms": pcm_convert_ms,
    }
    prefill_ms = _number_field(chunk_timing, "prefill_ms")
    decode_ms = _number_field(chunk_timing, "ar_decode_ms") or _number_field(
        chunk_timing, "decode_ms"
    )
    chunk_steps = _number_field(chunk_timing, "chunk_steps")

    if prefill_ms is not None:
        fields["prefill_ms"] = prefill_ms
    if decode_ms is not None:
        fields["ar_decode_ms"] = decode_ms
    if chunk_steps is not None:
        fields["chunk_steps"] = int(chunk_steps)
        if decode_ms is not None and chunk_steps > 0:
            fields["ar_ms_per_step"] = decode_ms / chunk_steps
    if stream_next_gpu_ms is not None:
        fields["stream_next_gpu_ms"] = stream_next_gpu_ms
        fields["stream_next_host_residual_ms"] = (
            next_wall_ms - stream_next_gpu_ms
        )
    if stream_next_gpu_ready is not None:
        fields["stream_next_gpu_ready"] = stream_next_gpu_ready

    for key in (
        "text_token_count",
        "instruction_token_count",
        "prefill_batch_size",
        "prefill_sequence_length",
        "talker_prefill_length",
        "profile_schema_version",
        "prefill_total_gpu_stream_id",
        "talker_forward_gpu_stream_id",
        "first_sample_gpu_stream_id",
        "prefill_kv_gpu_stream_id",
        "generation_state_gpu_stream_id",
        "prefill_to_sync_gpu_stream_id",
        "generation_state_masks_built",
        "prefill_compile_cache_entries",
        "prefill_compile_cache_entries_before",
        "prefill_compile_cache_entries_after",
        "prefill_compile_cache_entries_delta",
        "prefill_compile_cache_talker_entries",
        "prefill_compile_cache_talker_entries_before",
        "prefill_compile_cache_talker_entries_after",
        "prefill_compile_cache_talker_entries_delta",
        "prefill_compile_cache_max_entries",
        "prefill_compile_cache_evictions",
        "prefill_compile_cache_evictions_before",
        "prefill_compile_cache_evictions_after",
        "prefill_compile_cache_evictions_delta",
        "prefill_compile_attempt_count",
        "prefill_dynamo_unique_graphs_before",
        "prefill_dynamo_unique_graphs_after",
        "prefill_dynamo_unique_graphs_delta",
        "prefill_shape_call_ordinal",
        "prefill_shape_length",
        "prefix_split_probe_prefix_length",
        "voice_prefix_kv_reuse_prefix_length",
        "voice_prefix_kv_reuse_cache_entries",
        "chunk_target_steps",
        "chunk_schedule_index",
        "prefill_cuda_memory_before_allocated_bytes",
        "prefill_cuda_memory_before_reserved_bytes",
        "prefill_cuda_memory_before_max_reserved_bytes",
        "prefill_cuda_memory_after_allocated_bytes",
        "prefill_cuda_memory_after_reserved_bytes",
        "prefill_cuda_memory_after_max_reserved_bytes",
    ):
        value = _number_field(chunk_timing, key)
        if value is not None:
            fields[key] = int(value)
    for key in (
        "profile_path",
        "profile_status",
        "profile_request_role",
        "prefill_backend_requested",
        "prefill_backend_used",
        "voice_clone_prompt_mode",
        "voice_clone_prompt_source",
        "prefill_compile_error",
        "prefill_compile_compat_mode",
        "prefill_compile_cache_kind",
        "prefill_shape_policy",
        "chunk_schedule_decision",
        "prefill_mask_decision_source",
        "prefill_attn_implementation",
        "predictor_output_mode",
        "prefix_split_probe_error",
    ):
        value = chunk_timing.get(key)
        if isinstance(value, str):
            fields[key] = value
    for key in (
        "profile_prefill_enabled",
        "profile_complete",
        "events_complete",
        "components_finite",
        "components_nonnegative",
        "all_component_streams_equal",
        "prefill_compile_fallback",
        "prefill_compile_attempted",
        "prefill_compile_compat_applied",
        "prefill_compile_compat_reused",
        "prefill_compile_cache_hit",
        "prefill_shape_allowlist_hit",
        "prefill_compile_on_miss",
        "prefill_require_precompiled",
        "prefill_dynamo_counter_available",
        "generation_state_mask_cache_hit",
        "generation_state_attention_mask_all_valid",
        "prefill_attention_mask_all_valid",
        "prefill_has_sliding_window",
        "is_final",
        "stream_next_gpu_ready",
        "decode_backbone_compile_enabled",
        "prefix_split_probe_enabled",
        "prefix_split_probe_attempted",
        "prefix_split_probe_supported",
        "prefix_split_probe_logits_allclose",
        "prefix_split_probe_kv_allclose",
        "prefix_split_probe_first_token_match",
        "prefix_split_probe_prefix_kv_allclose",
        "prefix_split_probe_seeded_logits_allclose",
        "prefix_split_probe_seeded_first_token_match",
        "prefix_split_probe_seeded_kv_allclose",
        "voice_prefix_kv_reuse_enabled",
        "voice_prefix_kv_reuse_hit",
        "voice_prefix_kv_reuse_prefix_mismatch",
    ):
        value = chunk_timing.get(key)
        if isinstance(value, bool):
            fields[key] = value
    value = chunk_timing.get("prefill_compile_compat_patched_modules")
    if isinstance(value, dict):
        fields["prefill_compile_compat_patched_modules"] = dict(value)
    for key in (
        "selected_chunk_schedule",
        "ar_frame_timings",
        "talker_input_position_sha256",
        "prefill_shape_talker_input_embeds",
        "prefill_shape_attention_mask",
        "prefill_shape_trailing_text_hiddens",
        "prefill_shape_tts_pad_embed",
    ):
        value = chunk_timing.get(key)
        if isinstance(value, (list, tuple)):
            fields[key] = value
    for key in (
        "tokenize_wall_ms",
        "build_talker_inputs_wall_ms",
        "voice_clone_prompt_resolution_wall_ms",
        "prefill_total_gpu_ms",
        "talker_forward_launch_wall_ms",
        "talker_forward_gpu_ms",
        "first_sample_launch_wall_ms",
        "first_sample_gpu_ms",
        "prefill_kv_launch_wall_ms",
        "prefill_kv_gpu_ms",
        "generation_state_wall_ms",
        "generation_state_total_ms",
        "generation_state_mask_key_ms",
        "generation_state_mask_table_build_ms",
        "generation_state_rope_copy_ms",
        "generation_state_gpu_ms",
        "prefill_to_sync_gpu_ms",
        "prefill_sync_wait_ms",
        "prefill_gpu_component_sum_ms",
        "prefill_gpu_partition_error_ms",
        "prefill_gpu_accounting_error_ms",
        "prefill_compile_wall_ms",
        "prefill_compile_wrapper_create_ms",
        "prefill_compile_wrapper_create_host_ms",
        "prefill_compiled_call_ms",
        "prefill_compiled_call_host_ms",
        "prefill_compiled_first_call_ms",
        "prefill_compiled_warm_call_ms",
        "prefill_compiled_call_1_host_ms",
        "prefill_compiled_call_2_host_ms",
        "prefill_compiled_call_3plus_host_ms",
        "codec_context_assembly_ms",
        "speech_tokenizer_decode_wall_ms",
        "speech_tokenizer_decode_gpu_ms",
        "d2h_ms",
        "numpy_ms",
        "audio_flatten_ms",
        "audio_slice_ms",
        "codec_wrapper_wall_ms",
        "codec_wrapper_other_ms",
        "first_sample_setup_gpu_ms",
        "first_sample_logits_prepare_gpu_ms",
        "first_sample_clone_suppress_gpu_ms",
        "first_sample_temperature_gpu_ms",
        "first_sample_top_k_gpu_ms",
        "first_sample_top_p_gpu_ms",
        "first_sample_softmax_gpu_ms",
        "first_sample_multinomial_gpu_ms",
        "first_sample_argmax_gpu_ms",
        "ar_predictor_graph_gpu_ms",
        "ar_history_update_gpu_ms",
        "ar_codebook_embed_gather_gpu_ms",
        "ar_talker_graph_replay_gpu_ms",
        "ar_logits_prepare_gpu_ms",
        "ar_sample_clone_suppress_gpu_ms",
        "ar_sample_temperature_gpu_ms",
        "ar_sample_top_k_gpu_ms",
        "ar_sample_top_p_gpu_ms",
        "ar_sample_softmax_gpu_ms",
        "ar_sample_multinomial_gpu_ms",
        "ar_sample_argmax_gpu_ms",
        "ar_state_update_gpu_ms",
        "stream_next_gpu_ms",
        "stream_next_host_residual_ms",
        "prefix_split_probe_hidden_max_abs_delta",
        "prefix_split_probe_hidden_mean_abs_delta",
        "prefix_split_probe_prefix_hidden_max_abs_delta",
        "prefix_split_probe_prefix_hidden_mean_abs_delta",
        "prefix_split_probe_logits_max_abs_delta",
        "prefix_split_probe_kv_max_abs_delta",
        "prefix_split_probe_prefix_kv_max_abs_delta",
        "prefix_split_probe_seeded_hidden_max_abs_delta",
        "prefix_split_probe_seeded_hidden_mean_abs_delta",
        "prefix_split_probe_seeded_logits_max_abs_delta",
        "prefix_split_probe_seeded_kv_max_abs_delta",
    ):
        value = _number_field(chunk_timing, key)
        if value is not None:
            fields[key] = value
    for source_key, alias_key in (
        ("prefill_total_gpu_ms", "prefill_total_stream_elapsed_ms"),
        ("talker_forward_gpu_ms", "talker_forward_stream_elapsed_ms"),
        ("first_sample_gpu_ms", "first_sample_stream_elapsed_ms"),
        ("prefill_kv_gpu_ms", "prefill_kv_stream_elapsed_ms"),
        ("generation_state_gpu_ms", "generation_state_stream_elapsed_ms"),
        ("prefill_to_sync_gpu_ms", "prefill_to_sync_stream_elapsed_ms"),
    ):
        value = _number_field(chunk_timing, source_key)
        if value is not None:
            fields[alias_key] = value

    for key in (
        "generation_state_mask_key",
        "generation_state_previous_mask_key",
    ):
        if key in chunk_timing:
            value = chunk_timing.get(key)
            if value is None or isinstance(value, (list, tuple)):
                fields[key] = value

    residual_ms = next_wall_ms
    if prefill_ms is not None:
        residual_ms -= prefill_ms
    if decode_ms is not None:
        residual_ms -= decode_ms
    fields["codec_wrapper_residual_ms"] = residual_ms
    return fields


def _number_field(fields: dict[str, object], name: str) -> float | None:
    value = fields.get(name)
    if isinstance(value, (int, float)):
        return float(value)
    return None


class _StallTelemetry:
    """Optional per-chunk CUDA-event timing with no host synchronization.

    The default path owns no CUDA events and performs no GPU timing work.
    """

    def __init__(self, torch: Any | None) -> None:
        self._torch = torch
        self._start: Any | None = None

    def begin_chunk(self) -> None:
        if self._torch is None:
            return
        start = self._torch.cuda.Event(enable_timing=True)
        start.record()
        self._start = start

    def end_chunk(self) -> tuple[float | None, bool | None]:
        if self._torch is None or self._start is None:
            return None, None
        start = self._start
        end = self._torch.cuda.Event(enable_timing=True)
        end.record()
        if not end.query():
            return None, False
        return float(start.elapsed_time(end)), True


def _create_stall_telemetry() -> _StallTelemetry:
    """Return opt-in timing; explicit opt-in fails if CUDA timing is unavailable."""

    if os.environ.get("QTB_FASTER_STALL_TELEMETRY") != "1":
        return _StallTelemetry(None)
    try:
        torch = importlib.import_module("torch")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "QTB_FASTER_STALL_TELEMETRY=1 requires PyTorch with CUDA support"
        ) from exc
    if not torch.cuda.is_available():
        raise RuntimeError("QTB_FASTER_STALL_TELEMETRY=1 requires CUDA")
    return _StallTelemetry(torch)
