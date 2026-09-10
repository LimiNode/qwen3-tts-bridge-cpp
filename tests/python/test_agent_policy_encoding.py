"""Regression checks for the checked-in agent and code-quality guidance."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# These files are the canonical routing and quality-policy surface added in
# #76.  Keep this list explicit: historical research reports may legitimately
# contain quoted damaged input, but policy must remain readable and actionable.
POLICY_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".github/AGENTS.md",
    "docs/AGENTS.md",
    "docs/ai-code-quality.md",
    "docs/reports/ai-code-quality-review-20260909.md",
    "examples/AGENTS.md",
    "external/AGENTS.md",
    "scripts/AGENTS.md",
    "src/AGENTS.md",
    "src/qwen_tts_bridge/AGENTS.md",
    "src/qwen_tts_bridge/protocol/AGENTS.md",
    "src/qwen_tts_bridge/transport/AGENTS.md",
    "tests/AGENTS.md",
    "tests/python/AGENTS.md",
    "worker/AGENTS.md",
    "worker/native/AGENTS.md",
    "worker/src/qwen_tts_bridge_worker/AGENTS.md",
    "worker/src/qwen_tts_bridge_worker/protocol/AGENTS.md",
)

SUSPICIOUS_QUESTION_MARK = re.compile(r"\w\?\w|\?{4,}")


class AgentPolicyEncodingTests(unittest.TestCase):
    def test_policy_files_are_strict_utf8_without_replacement_characters(self) -> None:
        for relative_path in POLICY_FILES:
            with self.subTest(path=relative_path):
                content = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertNotIn("\ufffd", content)

    def test_policy_files_have_no_known_ascii_corruption_signature(self) -> None:
        for relative_path in POLICY_FILES:
            with self.subTest(path=relative_path):
                content = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIsNone(
                    SUSPICIOUS_QUESTION_MARK.search(content),
                    "question-mark corruption signature found",
                )


if __name__ == "__main__":
    unittest.main()
