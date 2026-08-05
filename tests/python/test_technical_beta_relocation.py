"""Static contracts for the portable technical-beta relocation smoke."""

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "test-technical-beta-relocation.ps1"
_PACKAGER = _ROOT / "scripts" / "package-technical-beta.ps1"
_PUBLISHER = _ROOT / "scripts" / "publish-technical-beta.ps1"
_FAULT_TEST = _ROOT / "scripts" / "test-technical-beta-publication.ps1"
_EVIDENCE_VERIFIER = _ROOT / "scripts" / "verify-technical-beta-acceptance-evidence.ps1"


class TechnicalBetaRelocationTests(unittest.TestCase):
    def test_relocation_smoke_covers_both_model_families(self) -> None:
        script = _SCRIPT.read_text(encoding="utf-8")

        self.assertIn("RelocationRoot must not already exist", script)
        self.assertIn("ReportPath must not already exist", script)
        self.assertIn("Split-Path -Parent $report", script)
        self.assertIn("$acceptancePass =", script)
        self.assertIn("required_gates = $requiredGates", script)
        self.assertIn("root_digest_algorithm", script)
        self.assertIn("scripts/package_tree_manifest.py", script)
        self.assertIn("scripts/voice_assets_manifest.py", script)
        self.assertIn("Assert-NativeClosure", script)
        self.assertIn("$env:PYTHONHOME", script)
        self.assertIn("$env:PYTHONPATH", script)
        self.assertIn("$env:HF_HUB_OFFLINE", script)
        self.assertIn("$env:TRANSFORMERS_OFFLINE", script)
        self.assertIn("Push-Location $worker", script)
        self.assertIn("--require-natural-eos", script)
        self.assertIn("--result-json", script)
        self.assertIn("Smoke result JSON does not prove", script)
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
        self.assertIn("Move-TechnicalBetaDirectoryAtomically", script)
        self.assertIn("Get-CleanSourceProvenance", script)
        self.assertIn("test-technical-beta-relocation.ps1", script)
        self.assertIn("-InPlace", script)
        self.assertIn("AcceptanceOutput already exists", script)
        self.assertIn(".__qtb-", script)
        self.assertIn("longestStagedDll", script)
        self.assertIn("too long for Windows DLL loading", script)
        self.assertIn("worker\\build-manifest.json", script)
        self.assertIn("UTF8Encoding]::new($false)", script)
        self.assertIn("published_destination", script)
        self.assertIn("immutable_tree_policy", script)
        self.assertIn(
            "Technical-beta publication requires a clean source worktree",
            script,
        )
        self.assertIn("source_diff_sha256", script)
        self.assertIn("Test-FaultInjectionReport", script)
        self.assertIn("candidate_root_digest", script)
        self.assertIn("published_root_digest", script)
        self.assertIn("required_gates = $requiredGates", script)

    def test_publication_fault_matrix_covers_atomic_replacement_boundaries(
        self,
    ) -> None:
        script = _FAULT_TEST.read_text(encoding="utf-8")

        self.assertIn("before_backup", script)
        self.assertIn("after_backup", script)
        self.assertIn("after_swap", script)
        self.assertIn("post_publish_validation", script)
        self.assertIn("before_backup_cleanup", script)
        self.assertIn("acceptance_pass = $acceptancePass", script)
        self.assertIn("final_marker", script)
        self.assertIn("Join-Path (Get-Location).Path $Path", script)

    def test_evidence_verifier_derives_r3_gates_without_rewriting_history(
        self,
    ) -> None:
        script = _EVIDENCE_VERIFIER.read_text(encoding="utf-8")

        self.assertIn("Evidence verification requires a clean source worktree", script)
        self.assertIn("Test-NaturalEos", script)
        self.assertIn("candidate_published_root_digest_match", script)
        self.assertIn("publication_fault_injection", script)
        self.assertIn("original_acceptance_tooling_commit", script)
        self.assertIn("evidence_augmentation", script)
        self.assertIn("Join-Path (Get-Location).Path $Output", script)


if __name__ == "__main__":
    unittest.main()
