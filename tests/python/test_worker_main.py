import io
import unittest
from typing import BinaryIO, TextIO
from unittest.mock import patch

from qwen_tts_bridge_worker import main as worker_main


class _FakeTextStream:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()
        self.text = io.StringIO()

    def write(self, value: str) -> int:
        return self.text.write(value)

    def flush(self) -> None:
        self.text.flush()


class _CapturingServer:
    instances: list["_CapturingServer"] = []

    def __init__(
        self,
        *,
        input_stream: BinaryIO,
        output_stream: BinaryIO,
        error_stream: TextIO,
        engine: object,
        worker_version: str,
        output_queue_size: int,
    ) -> None:
        self.input_stream = input_stream
        self.output_stream = output_stream
        self.error_stream = error_stream
        self.stdout_during_run: object | None = None
        _CapturingServer.instances.append(self)

    def run(self) -> int:
        self.stdout_during_run = worker_main.sys.stdout
        print("third-party stdout noise")
        return 0


class WorkerMainTests(unittest.TestCase):
    def setUp(self) -> None:
        _CapturingServer.instances.clear()

    def test_main_redirects_print_stdout_away_from_protocol_stream(self) -> None:
        stdin = _FakeTextStream()
        stdout = _FakeTextStream()
        stderr = _FakeTextStream()

        with (
            patch.object(worker_main.sys, "stdin", stdin),
            patch.object(worker_main.sys, "stdout", stdout),
            patch.object(worker_main.sys, "stderr", stderr),
            patch.object(worker_main, "StdioWorkerServer", _CapturingServer),
        ):
            exit_code = worker_main.main(["mock"])

            self.assertEqual(0, exit_code)
            self.assertEqual(1, len(_CapturingServer.instances))
            server = _CapturingServer.instances[0]
            self.assertIs(stdout.buffer, server.output_stream)
            self.assertIs(stderr, server.stdout_during_run)
            self.assertEqual(b"", stdout.buffer.getvalue())
            self.assertIn("third-party stdout noise", stderr.text.getvalue())


if __name__ == "__main__":
    unittest.main()
