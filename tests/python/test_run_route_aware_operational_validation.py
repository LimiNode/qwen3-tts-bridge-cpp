from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_route_aware_operational_validation import (
    Operation,
    _load_request_specs,
    _operations,
)


class RouteAwareOperationalValidationTests(unittest.TestCase):
    def test_loads_manifest_speaker_and_optional_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requests.jsonl"
            path.write_text(
                "\n".join(
                    (
                        json.dumps({"text": "first", "speaker": "serena", "seed": 44}),
                        json.dumps({"text": "second"}),
                    )
                ),
                encoding="utf-8",
            )

            specifications = _load_request_specs(path)

        self.assertEqual(
            [
                Operation(outcome="", text="first", speaker="serena", seed=44),
                Operation(outcome="", text="second", speaker="ryan", seed=None),
            ],
            specifications,
        )

    def test_operations_preserve_manifest_identity(self) -> None:
        specifications = [
            Operation(outcome="", text="first", speaker="serena", seed=44),
            Operation(outcome="", text="second", speaker="ryan", seed=None),
        ]

        operations = _operations(
            specifications,
            completed=1,
            cancelled_before_audio=1,
            cancelled_after_audio=1,
            failed=1,
        )

        self.assertEqual(
            [
                Operation(outcome="completed", text="first", speaker="serena", seed=44),
                Operation(
                    outcome="cancelled_before_audio",
                    text="second",
                    speaker="ryan",
                    seed=None,
                ),
                Operation(
                    outcome="cancelled_after_audio",
                    text="first",
                    speaker="serena",
                    seed=44,
                ),
                Operation(outcome="failed", text=None),
            ],
            operations,
        )


if __name__ == "__main__":
    unittest.main()
