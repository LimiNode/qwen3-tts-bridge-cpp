"""Tests for the repeat manifest transformer."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "prepare_synthetic_proxy_repeat.py"
)
_SPEC = importlib.util.spec_from_file_location("prepare_repeat", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class PrepareSyntheticProxyRepeatTests(unittest.TestCase):
    def test_repeat_label_preserves_the_source_corpus_identity(self) -> None:
        self.assertEqual(
            _MODULE._repeat_label({"corpus_id": "streamer-game-voice-natural-v2"}, 7),
            "streamer-game-voice-natural-v2-repeat-0007",
        )

    def test_repeat_label_has_a_neutral_fallback(self) -> None:
        self.assertEqual(_MODULE._repeat_label({}, 2), "repeat-0002")


if __name__ == "__main__":
    unittest.main()
