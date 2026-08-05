"""Static contracts for the portable technical-beta relocation smoke."""

from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "test-technical-beta-relocation.ps1"


class TechnicalBetaRelocationTests(unittest.TestCase):
    def test_relocation_smoke_uses_private_runtime_and_eos_gate(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")

        self.assertIn("RelocationRoot must not already exist", script)
        self.assertIn("scripts/package_tree_manifest.py", script)
        self.assertIn("scripts/voice_assets_manifest.py", script)
        self.assertIn("Assert-NativeClosure", script)
        self.assertIn("$env:PYTHONHOME", script)
        self.assertIn("$env:PYTHONPATH", script)
        self.assertIn("--require-natural-eos", script)
        self.assertIn("Relocated package wrote Python bytecode", script)


if __name__ == "__main__":
    unittest.main()
