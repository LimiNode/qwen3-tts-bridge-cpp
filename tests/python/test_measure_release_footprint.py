from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "measure-release-footprint.py"
)
_SPEC = importlib.util.spec_from_file_location("measure_release_footprint", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
measure = _MODULE.measure


class ReleaseFootprintTests(unittest.TestCase):
    def test_directory_and_zip_report_unpacked_and_archive_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            root.mkdir()
            (root / "bin").mkdir()
            (root / "bin" / "worker.exe").write_bytes(b"worker")
            (root / "config.json").write_text("{}", encoding="utf-8")

            directory_result = measure(root)
            self.assertEqual(directory_result["file_count"], 2)
            self.assertEqual(directory_result["unpacked_bytes"], 8)

            archive = Path(temporary) / "package.zip"
            with zipfile.ZipFile(archive, "w") as output:
                for path in root.rglob("*"):
                    if path.is_file():
                        output.write(path, path.relative_to(root).as_posix())
            archive_result = measure(archive)
            self.assertEqual(archive_result["input_kind"], "zip")
            self.assertEqual(archive_result["file_count"], 2)
            self.assertEqual(archive_result["unpacked_bytes"], 8)
            self.assertGreater(archive_result["archive_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
