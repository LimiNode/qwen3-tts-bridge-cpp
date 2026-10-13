"""Minimal mock worker that records the decoded request text and instruction."""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterable
from pathlib import Path

# The C++ transport intentionally inherits the parent environment. Resolve the
# source checkout explicitly as a fallback so this standalone test worker does
# not depend on an editable Python install or a launcher-specific PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker" / "src"))

from qwen_tts_bridge_worker.engine.mock_engine import MockTtsEngine
from qwen_tts_bridge_worker.engine.types import SynthesisRequest
from qwen_tts_bridge_worker.server.stdio_server import StdioWorkerServer


class CaptureEngine(MockTtsEngine):
    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        capture_path = os.environ.get("QTB_UTF8_CAPTURE_PATH")
        if not capture_path:
            raise RuntimeError("QTB_UTF8_CAPTURE_PATH is required")
        Path(capture_path).write_bytes(
            json.dumps(
                {
                    "text": request.text,
                    "instruction": request.instruction,
                    "text_utf8": request.text.encode("utf-8").hex(),
                    "instruction_utf8": request.instruction.encode("utf-8").hex(),
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )
        yield from super().synthesize_stream(request, cancel_event)


def main() -> int:
    server = StdioWorkerServer(
        input_stream=sys.stdin.buffer,
        output_stream=sys.stdout.buffer,
        error_stream=sys.stderr,
        engine=CaptureEngine(chunk_count=1, chunk_duration_ms=40),
    )
    return server.run()


if __name__ == "__main__":
    raise SystemExit(main())
