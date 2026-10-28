"""Controlled protocol worker for completion-receipt integration tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker" / "src"))

from qwen_tts_bridge_worker.engine.mock_engine import MockTtsEngine
from qwen_tts_bridge_worker.server.stdio_server import StdioWorkerServer


class ControlledTraceEngine(MockTtsEngine):
    """Return a selected terminal trace after deterministic mock audio."""

    def __init__(self, mode: str) -> None:
        super().__init__(chunk_count=1, chunk_duration_ms=40)
        self._mode = mode

    def pop_last_generation_trace(self) -> dict[str, object] | None:
        trace = super().pop_last_generation_trace()
        if self._mode == "absent":
            return None
        if trace is None:
            return None
        if self._mode == "eos":
            return trace
        trace["termination_reason"] = self._mode
        trace["hit_eos"] = False
        trace["hit_max_new_tokens"] = self._mode == "max_new_tokens"
        trace["hit_max_seq_len"] = self._mode == "max_seq_len"
        return trace


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "eos"
    if mode not in {"absent", "eos", "max_new_tokens", "max_seq_len", "other"}:
        raise ValueError(f"unsupported trace mode: {mode}")
    server = StdioWorkerServer(
        input_stream=sys.stdin.buffer,
        output_stream=sys.stdout.buffer,
        error_stream=sys.stderr,
        engine=ControlledTraceEngine(mode),
    )
    return server.run()


if __name__ == "__main__":
    raise SystemExit(main())
