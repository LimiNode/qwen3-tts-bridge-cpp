import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.qwen_exact_allowlist_prime_matrix import run_matrix


class ExactAllowlistPrimeMatrixTests(unittest.TestCase):
    def test_matrix_materializes_all_prime_and_decode_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            eager = root / "eager.json"
            compiled = root / "compiled.json"
            output = root / "report.json"
            for path in (manifest, eager, compiled):
                path.write_text("{}\n", encoding="utf-8")

            def fake_run(command: list[str], check: bool) -> object:
                output_path = Path(command[command.index("--output") + 1])
                parity_pass = "prime-on" in output_path.stem
                output_path.write_text(
                    json.dumps({"passed": parity_pass}), encoding="utf-8"
                )
                return argparse.Namespace(returncode=0 if parity_pass else 1)

            args = argparse.Namespace(
                manifest=manifest,
                eager_profile=eager,
                compiled_profile=compiled,
                speaker="ryan",
                seed_start=100,
                sampling_seed_count=5,
                greedy_seed_count=3,
                resume=False,
                output=output,
            )
            with patch(
                "scripts.qwen_exact_allowlist_prime_matrix.subprocess.run",
                side_effect=fake_run,
            ):
                report = run_matrix(args)

            self.assertTrue(report["passed"])
            cases = report["cases"]
            assert isinstance(cases, list)
            self.assertEqual(4, len(cases))
            self.assertEqual(
                {
                    "sampling-prime-off",
                    "sampling-prime-on",
                    "greedy-prime-off",
                    "greedy-prime-on",
                },
                {case["name"] for case in cases},
            )


if __name__ == "__main__":
    unittest.main()
