"""Check the native preparation seam without loading models or a native DLL."""

import io
import unittest

from qwen_tts_bridge_worker.voice_library import VoiceLibraryError, _run_native_prepare
from qwen_tts_bridge_worker.voice_library_errors import (
    VoiceLibraryError as NativePreparationError,
)
from qwen_tts_bridge_worker.voice_native_prepare import (
    _frame,
    _read_frame_blocking,
    run_native_prepare,
)


class NativePreparationBoundaryTests(unittest.TestCase):
    def test_existing_entry_points_keep_the_same_error_and_operation(self) -> None:
        self.assertIs(VoiceLibraryError, NativePreparationError)
        self.assertIs(_run_native_prepare, run_native_prepare)

    def test_native_control_frame_round_trip_preserves_unicode(self) -> None:
        payload = {"message_type": "hello", "client_name": "голос"}
        self.assertEqual(payload, _read_frame_blocking(io.BytesIO(_frame(payload))))

    def test_malformed_frame_raises_the_existing_library_error(self) -> None:
        with self.assertRaisesRegex(VoiceLibraryError, "invalid protocol frame"):
            _read_frame_blocking(io.BytesIO(b"invalid" * 4))
