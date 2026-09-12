"""Unit tests for the fail-closed native hardware probe primitives."""

from __future__ import annotations

import importlib.util
import io
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "run_native_hardware_probe", ROOT / "scripts" / "run-native-hardware-probe.py"
)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class NativeHardwareProbeTests(unittest.TestCase):
    def test_read_frame_decodes_control_payload(self) -> None:
        payload = {"message_type": "completed", "execution_outcome": "natural_eos"}
        encoded = probe.frame(7, payload)

        frame_type, request_id, decoded = probe.read_frame(io.BytesIO(encoded))

        self.assertEqual(1, frame_type)
        self.assertEqual(7, request_id)
        self.assertEqual(payload, decoded)

    def test_read_frame_rejects_oversized_payload(self) -> None:
        header = probe.HEADER.pack(
            b"QTB1", 1, probe.HEADER.size, 1, 0, probe.MAX_FRAME_PAYLOAD + 1, 1
        )

        with self.assertRaisesRegex(RuntimeError, "oversized"):
            probe.read_frame(io.BytesIO(header))

    def test_probe_source_keeps_acceptance_gates(self) -> None:
        source = (ROOT / "scripts" / "run-native-hardware-probe.py").read_text(encoding="utf-8")

        for required in (
            'message_type") != "completed"',
            "execution_outcome",
            '"starvation_detected"',
            '"buffer_slack_ms"',
            '"hashes"',
            'stderr_thread.join',
        ):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
