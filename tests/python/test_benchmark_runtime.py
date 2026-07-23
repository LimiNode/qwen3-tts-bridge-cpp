import tempfile
import unittest
from pathlib import Path

import benchmark_runtime as br


class BenchmarkRuntimeTests(unittest.TestCase):
    def test_source_git_is_suppressed_inside_virtual_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            venv = Path(temp) / ".venv-packaging"
            package = venv / "Lib" / "site-packages" / "faster_qwen3_tts"
            package.mkdir(parents=True)
            (venv / "pyvenv.cfg").write_text("", encoding="utf-8")

            self.assertIsNone(br._source_git_info(package))

    def test_matching_retained_wheels_reports_sha256(self) -> None:
        old_repo_root = br._REPO_ROOT
        with tempfile.TemporaryDirectory() as temp:
            try:
                br._REPO_ROOT = Path(temp)
                wheels = (
                    br._REPO_ROOT
                    / "dist"
                    / "QwenTTSBridge"
                    / "worker-python"
                    / "wheels"
                )
                wheels.mkdir(parents=True)
                wheel = wheels / "faster_qwen3_tts-0.3.2-py3-none-any.whl"
                wheel.write_bytes(b"abc")

                matches = br._matching_retained_wheels("faster-qwen3-tts", "0.3.2")
            finally:
                br._REPO_ROOT = old_repo_root

        self.assertEqual(1, len(matches))
        self.assertEqual(str(wheel), matches[0]["file"])
        self.assertEqual(3, matches[0]["size_bytes"])
        self.assertEqual(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            matches[0]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
