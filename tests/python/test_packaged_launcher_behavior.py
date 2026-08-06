"""Windows behavior checks for the sealed packaged playback launcher."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _ROOT / "scripts" / "start-packaged-qwen-tts.ps1"


@unittest.skipUnless(os.name == "nt", "the packaged launcher is Windows-only")
class PackagedLauncherBehaviorTests(unittest.TestCase):
    def test_initialization_rejects_package_local_config_paths(self) -> None:
        with _fake_package() as package:
            local_app_data = package.parent / "local-app-data"
            external = local_app_data / "QwenTTSBridge" / "runtime.local.json"
            result = _run_launcher(
                package,
                "-InitializeConfig",
                environment={"LOCALAPPDATA": str(local_app_data)},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(external.is_file())

            for path in (
                package / "runtime.local.json",
                package / "config" / "nested.local.json",
                package / "config" / ".." / "runtime.local.json",
            ):
                result = _run_launcher(
                    package, "-UserConfigPath", path, "-InitializeConfig"
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("outside the sealed package root", result.stderr)
                self.assertFalse(path.resolve().exists())

    def test_dry_run_validates_schema_duplicate_keys_and_timeout(self) -> None:
        with _fake_package() as package:
            config = package.parent / "runtime.local.json"
            _write_config(config, schema_version=1, timeout=180000)
            result = _run_launcher(package, "-UserConfigPath", config, "-DryRun")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("--startup-timeout-ms | 180000", result.stdout)

            result = _run_launcher(
                package,
                "-UserConfigPath",
                config,
                "-StartupTimeoutMs",
                "200000",
                "-DryRun",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("--startup-timeout-ms | 200000", result.stdout)

            _write_config(config, schema_version=2, timeout=180000)
            result = _run_launcher(package, "-UserConfigPath", config, "-DryRun")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("schema_version must be the integer 1", result.stderr)

            config.write_text(
                '{"schema_version":1,"schema_version":1}', encoding="utf-8"
            )
            result = _run_launcher(package, "-UserConfigPath", config, "-DryRun")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("duplicate JSON keys", result.stderr)


class _fake_package:
    def __enter__(self) -> Path:
        self._temporary = tempfile.TemporaryDirectory()
        temporary_root = Path(self._temporary.name)
        self.package = temporary_root / "package"
        (self.package / "config").mkdir(parents=True)
        (self.package / "bin").mkdir()
        (self.package / "worker").mkdir()
        (self.package / "models").mkdir()
        (self.package / ".qtb-technical-beta-root").write_text("marker\n")
        (self.package / "config" / "runtime.local.example.json").write_text(
            json.dumps(_config_data(1, 180000)), encoding="utf-8"
        )
        (self.package / "config" / "voice-profiles.json").write_text("{}\n")
        shutil.copyfile(
            os.environ["COMSPEC"], self.package / "bin" / "qwen_tts_play.exe"
        )
        worker_python = self.package / "worker" / "python"
        worker_python.mkdir()
        os.link(sys.executable, worker_python / "python.exe")
        shutil.copyfile(Path(sys.prefix) / "pyvenv.cfg", worker_python / "pyvenv.cfg")
        return self.package

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()


def _config_data(schema_version: int, timeout: int) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "runtime_backend": "faster",
        "startup_timeout_ms": timeout,
        "custom_voice_model_path": "",
        "base_model_path": "",
        "custom_voice_speaker": "serena",
        "base_voice_id": "robot",
        "language": "auto",
        "dtype": "bfloat16",
    }


def _write_config(path: Path, *, schema_version: int, timeout: int) -> None:
    path.write_text(json.dumps(_config_data(schema_version, timeout)), encoding="utf-8")


def _run_launcher(
    package: Path,
    *arguments: object,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(_LAUNCHER),
        "-PackageRoot",
        str(package),
        "-ModelPath",
        str(package / "models"),
    ] + [str(argument) for argument in arguments]
    process_environment = os.environ.copy()
    if environment:
        process_environment.update(environment)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=process_environment,
    )
