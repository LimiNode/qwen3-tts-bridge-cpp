"""Static contracts for the portable technical-beta relocation smoke."""

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "test-technical-beta-relocation.ps1"
_PACKAGER = _ROOT / "scripts" / "package-technical-beta.ps1"
_PUBLISHER = _ROOT / "scripts" / "publish-technical-beta.ps1"


class TechnicalBetaRelocationTests(unittest.TestCase):
    def test_relocation_smoke_covers_both_model_families(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")

        self.assertIn("RelocationRoot must not already exist", script)
        self.assertIn("ReportPath must not already exist", script)
        self.assertIn("scripts/package_tree_manifest.py", script)
        self.assertIn("scripts/voice_assets_manifest.py", script)
        self.assertIn("Assert-NativeClosure", script)
        self.assertIn("$env:PYTHONHOME", script)
        self.assertIn("$env:PYTHONPATH", script)
        self.assertIn("--require-natural-eos", script)
        self.assertIn("$baseModel", script)
        self.assertIn("--voice-registry", script)
        self.assertIn("doctor_base", script)
        self.assertIn("Relocated package wrote Python bytecode", script)

    def test_clean_replacement_keeps_old_package_until_staging_succeeds(
        self,
    ) -> None:
        script = _PACKAGER.read_text(encoding="utf-8")

        self.assertNotIn(
            "Remove-Item -LiteralPath $FinalRoot -Recurse -Force",
            script,
        )
        self.assertIn("$FinalRoot.backup-", script)
        self.assertIn(
            "Move-Item -LiteralPath $StageRoot -Destination $FinalRoot",
            script,
        )
        self.assertIn(
            "Move-Item -LiteralPath $BackupRoot -Destination $FinalRoot",
            script,
        )

    def test_publisher_requires_relocated_acceptance_before_publishing(self) -> None:
        script = _PUBLISHER.read_text(encoding="utf-8")

        self.assertIn("package-technical-beta.ps1", script)
        self.assertIn("test-technical-beta-relocation.ps1", script)
        self.assertIn("Replace-DirectoryAtomically", script)
        self.assertIn("AcceptanceOutput already exists", script)
        self.assertIn(".qtb-publish-", script)
        self.assertIn("custom_voice_natural_eos_sha256", script)
        self.assertIn("base_natural_eos_sha256", script)


if __name__ == "__main__":
    unittest.main()
