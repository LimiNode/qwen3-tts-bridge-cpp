"""Tests for fail-closed release-soak revalidation provenance."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.validate_qwen_release_soak_report import _expected_context


class ValidateReleaseSoakReportTests(unittest.TestCase):
    def test_uses_schedule_labels_not_observed_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schedule = root / "schedule.jsonl"
            seeds = root / "seeds.json"
            schedule.write_text(
                "{\"label\":\"compiled_32\",\"text\":\"one\"}\n"
                "{\"label\":\"unknown_31\",\"text\":\"two\"}\n",
                encoding="utf-8",
            )
            seeds.write_text("{\"seeds\":[1,2]}", encoding="utf-8")
            config = {
                "schedule": str(schedule),
                "seed_manifest": str(seeds),
                "required_label": [],
            }

            context = _expected_context(config, schedule=schedule, seed_manifest=seeds)

        self.assertEqual(["compiled_32", "unknown_31"], context["labels"])
        self.assertIn("sha256", context["schedule"])

    def test_rejects_manifest_different_from_raw_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured_schedule = root / "configured.jsonl"
            supplied_schedule = root / "supplied.jsonl"
            seeds = root / "seeds.json"
            configured_schedule.write_text(
                "{\"label\":\"compiled_32\",\"text\":\"one\"}\n",
                encoding="utf-8",
            )
            supplied_schedule.write_text(
                "{\"label\":\"unknown_31\",\"text\":\"two\"}\n",
                encoding="utf-8",
            )
            seeds.write_text("{\"seeds\":[1,2]}", encoding="utf-8")
            config = {
                "schedule": str(configured_schedule),
                "seed_manifest": str(seeds),
                "required_label": [],
            }

            with self.assertRaisesRegex(RuntimeError, "schedule does not match"):
                _expected_context(
                    config,
                    schedule=supplied_schedule,
                    seed_manifest=seeds,
                )


if __name__ == "__main__":
    unittest.main()
