"""Tests for the bootstrap voice-clone candidate runner contracts."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


def _load_runner() -> Any:
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "run-voice-clone-bootstrap-candidates.py"
    )
    spec = importlib.util.spec_from_file_location("bootstrap_candidate_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load bootstrap candidate runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _experiment_contract() -> dict[str, object]:
    return {"schema_version": 2, "runner": {"sha256": "a" * 64}}


def _candidate_contract(experiment_contract: dict[str, object]) -> dict[str, object]:
    return {
        "experiment_contract_sha256": RUNNER._sha256(
            RUNNER._canonical_json_bytes(experiment_contract)
        ),
        "voice_id": "test",
        "seed": 7,
    }


def _stream_outcome() -> dict[str, object]:
    return {
        "stream_exhausted": True,
        "safety_truncated": False,
        "final_metadata": {
            "is_final": True,
            "termination_reason": "eos",
            "hit_eos": True,
            "hit_max_new_tokens": False,
            "hit_max_seq_len": False,
            "terminal_step_index": 32,
            "generated_steps": 32,
            "emitted_steps": 32,
        },
    }


def _trace() -> dict[str, object]:
    return {
        "trace_kind": "voice_clone_streaming_v1",
        "generated_codec_sha256": "a" * 64,
        "generated_codec_frame_count": 32,
        "terminal_step_index": 32,
        "generated_steps": 32,
        "emitted_steps": 32,
        "hit_eos": True,
        "hit_max_new_tokens": False,
        "hit_max_seq_len": False,
    }


class BootstrapCandidateRunnerTests(unittest.TestCase):
    def test_terminal_outcome_requires_eos_trace_and_reset(self) -> None:
        outcome = RUNNER._terminal_outcome(
            _stream_outcome(),
            _trace(),
            {
                "talker_graph_reset": True,
                "predictor_graphs_reset": 2,
                "diagnostic_reset_state": {
                    "talker_static_cache_sequence_length": 0,
                    "predictor_static_cache_sequence_lengths": [0, 0],
                },
            },
        )

        self.assertEqual("completed", outcome["status"])
        self.assertTrue(outcome["passed"])
        self.assertEqual([], outcome["failures"])

    def test_terminal_outcome_rejects_safety_or_budget_truncation(self) -> None:
        outcome = RUNNER._terminal_outcome(
            {
                "stream_exhausted": False,
                "safety_truncated": True,
                "final_metadata": {
                    "is_final": True,
                    "termination_reason": "max_new_tokens",
                    "hit_eos": False,
                    "hit_max_new_tokens": True,
                    "hit_max_seq_len": False,
                },
            },
            {},
            {},
        )

        self.assertEqual("failed", outcome["status"])
        self.assertFalse(outcome["passed"])
        self.assertIn("safety_truncated", outcome["failures"])
        self.assertIn("terminal_reason_not_eos", outcome["failures"])
        self.assertIn("terminal_hit_max_new_tokens", outcome["failures"])
        self.assertIn("generation_trace_incomplete", outcome["failures"])
        self.assertIn("generation_reset_incomplete", outcome["failures"])

    def test_resume_requires_matching_completed_sidecar(self) -> None:
        experiment_contract = _experiment_contract()
        contract = _candidate_contract(experiment_contract)
        pcm = b"\x00\x00\x10\x00"
        stream_outcome = _stream_outcome()
        trace = _trace()
        reset = {
            "talker_graph_reset": True,
            "predictor_graphs_reset": 2,
            "diagnostic_reset_state": {
                "talker_static_cache_sequence_length": 0,
                "predictor_static_cache_sequence_lengths": [0, 0],
            },
        }
        terminal = RUNNER._terminal_outcome(stream_outcome, trace, reset)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "candidate.wav"
            RUNNER._write_wav(output_path, pcm, 24_000)
            with self.assertRaisesRegex(ValueError, "requires candidate sidecar"):
                RUNNER._read_existing(output_path, contract, experiment_contract)
            RUNNER._write_json(
                RUNNER._sidecar_path(output_path),
                {
                    "schema_version": 4,
                    "candidate_contract": contract,
                    "experiment_contract": experiment_contract,
                    "status": "completed",
                    "stream_outcome": stream_outcome,
                    "trace": trace,
                    "reset": reset,
                    "terminal": terminal,
                    "pcm_sha256": RUNNER._sha256(pcm),
                    "pcm_bytes": len(pcm),
                    "sample_rate": 24_000,
                    "wav_sha256": RUNNER._sha256_file(output_path),
                },
            )

            resumed = RUNNER._read_existing(
                output_path,
                contract,
                experiment_contract,
            )
            self.assertEqual("resumed", resumed["status"])

            tampered_contract = {
                "schema_version": 2,
                "runner": {"sha256": "b" * 64},
            }
            RUNNER._write_json(
                RUNNER._sidecar_path(output_path),
                {
                    "schema_version": 4,
                    "candidate_contract": contract,
                    "experiment_contract": tampered_contract,
                    "status": "completed",
                    "stream_outcome": stream_outcome,
                    "trace": trace,
                    "reset": reset,
                    "terminal": terminal,
                    "pcm_sha256": RUNNER._sha256(pcm),
                    "pcm_bytes": len(pcm),
                    "sample_rate": 24_000,
                    "wav_sha256": RUNNER._sha256_file(output_path),
                },
            )
            with self.assertRaisesRegex(ValueError, "contract SHA is invalid"):
                RUNNER._read_existing(output_path, contract, experiment_contract)

            RUNNER._write_json(
                RUNNER._sidecar_path(output_path),
                {
                    "schema_version": 4,
                    "candidate_contract": contract,
                    "experiment_contract": experiment_contract,
                    "status": "completed",
                    "stream_outcome": stream_outcome,
                    "trace": trace,
                    "reset": reset,
                    "terminal": terminal,
                    "pcm_sha256": RUNNER._sha256(pcm),
                    "pcm_bytes": len(pcm),
                    "sample_rate": 24_000,
                    "wav_sha256": RUNNER._sha256_file(output_path),
                },
            )
            with self.assertRaisesRegex(ValueError, "does not match"):
                RUNNER._read_existing(
                    output_path,
                    {**contract, "experiment_contract_sha256": "b" * 64},
                    experiment_contract,
                )

            reset["diagnostic_reset_state"] = {
                "talker_static_cache_sequence_length": 1,
                "predictor_static_cache_sequence_lengths": [0, 0],
            }
            RUNNER._write_json(
                RUNNER._sidecar_path(output_path),
                {
                    "schema_version": 4,
                    "candidate_contract": contract,
                    "experiment_contract": experiment_contract,
                    "status": "completed",
                    "stream_outcome": stream_outcome,
                    "trace": trace,
                    "reset": reset,
                    "terminal": terminal,
                    "pcm_sha256": RUNNER._sha256(pcm),
                    "pcm_bytes": len(pcm),
                    "sample_rate": 24_000,
                    "wav_sha256": RUNNER._sha256_file(output_path),
                },
            )
            with self.assertRaisesRegex(ValueError, "terminal evidence does not pass"):
                RUNNER._read_existing(output_path, contract, experiment_contract)

    def test_generation_resets_graphs_after_consume_failure(self) -> None:
        class FakeModel:
            def __init__(self) -> None:
                self.reset_calls = 0

            def generate_voice_clone_streaming(self, **_kwargs: object) -> object:
                return object()

            def reset_after_partial_generation(self) -> dict[str, object]:
                self.reset_calls += 1
                return {"talker_graph_reset": True, "predictor_graphs_reset": 2}

        model = FakeModel()
        arguments = SimpleNamespace(
            text="test",
            chunk_frames=8,
            max_new_tokens=512,
            temperature=0.4,
            top_k=50,
            top_p=1.0,
            repetition_penalty=1.05,
            max_audio_seconds=30.0,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(RUNNER, "_seed"),
                patch.object(RUNNER, "_sync_cuda"),
                patch.object(
                    RUNNER,
                    "_consume",
                    side_effect=RuntimeError("consume failed"),
                ),
                self.assertRaisesRegex(RuntimeError, "consume failed"),
            ):
                RUNNER._generate_one(
                    model=model,
                    np=object(),
                    torch=object(),
                    prompt=object(),
                    output_path=Path(temporary_directory) / "candidate.wav",
                    seed=7,
                    candidate_contract={"voice_id": "test", "seed": 7},
                    experiment_contract={},
                    experiment_locations={},
                    args=arguments,
                )

        self.assertEqual(1, model.reset_calls)

    def test_generation_resets_graphs_when_stream_close_fails(self) -> None:
        class FailingCloseStream:
            def close(self) -> None:
                raise RuntimeError("close failed")

        class FakeModel:
            def __init__(self) -> None:
                self.reset_calls = 0

            def generate_voice_clone_streaming(self, **_kwargs: object) -> object:
                return FailingCloseStream()

            def reset_after_partial_generation(self) -> dict[str, object]:
                self.reset_calls += 1
                return {"talker_graph_reset": True, "predictor_graphs_reset": 2}

        arguments = SimpleNamespace(
            text="test",
            chunk_frames=8,
            max_new_tokens=512,
            temperature=0.4,
            top_k=50,
            top_p=1.0,
            repetition_penalty=1.05,
            max_audio_seconds=30.0,
        )
        model = FakeModel()
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(RUNNER, "_seed"),
                patch.object(RUNNER, "_sync_cuda"),
                patch.object(
                    RUNNER,
                    "_consume",
                    return_value=(b"\x00\x00", 24_000, {}),
                ),
                self.assertRaisesRegex(RuntimeError, "close failed"),
            ):
                RUNNER._generate_one(
                    model=model,
                    np=object(),
                    torch=object(),
                    prompt=object(),
                    output_path=Path(temporary_directory) / "candidate.wav",
                    seed=7,
                    candidate_contract={"voice_id": "test", "seed": 7},
                    experiment_contract={},
                    experiment_locations={},
                    args=arguments,
                )

        self.assertEqual(1, model.reset_calls)

    def test_generation_preserves_primary_and_cleanup_errors(self) -> None:
        class FailingCloseStream:
            def close(self) -> None:
                raise RuntimeError("close failed")

        class FakeModel:
            def __init__(self) -> None:
                self.reset_calls = 0

            def generate_voice_clone_streaming(self, **_kwargs: object) -> object:
                return FailingCloseStream()

            def reset_after_partial_generation(self) -> dict[str, object]:
                self.reset_calls += 1
                return {"talker_graph_reset": True, "predictor_graphs_reset": 2}

        arguments = SimpleNamespace(
            text="test",
            chunk_frames=8,
            max_new_tokens=512,
            temperature=0.4,
            top_k=50,
            top_p=1.0,
            repetition_penalty=1.05,
            max_audio_seconds=30.0,
        )
        model = FakeModel()
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(RUNNER, "_seed"),
                patch.object(RUNNER, "_sync_cuda"),
                patch.object(
                    RUNNER,
                    "_consume",
                    side_effect=RuntimeError("consume failed"),
                ),
                self.assertRaises(BaseExceptionGroup) as caught,
            ):
                RUNNER._generate_one(
                    model=model,
                    np=object(),
                    torch=object(),
                    prompt=object(),
                    output_path=Path(temporary_directory) / "candidate.wav",
                    seed=7,
                    candidate_contract={"voice_id": "test", "seed": 7},
                    experiment_contract={},
                    experiment_locations={},
                    args=arguments,
                )

        self.assertEqual(1, model.reset_calls)
        self.assertEqual(
            ["consume failed", "close failed"],
            [str(error) for error in caught.exception.exceptions],
        )


if __name__ == "__main__":
    unittest.main()
