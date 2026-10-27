"""Release-facing QwenTTSBridge command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from qwen_tts_bridge_worker.model_resolver import (
    MODEL_CATALOG,
    default_user_config_path,
    download_model,
    list_models,
    load_user_config,
    resolve_model,
    resolve_native_profile,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the user-facing CLI."""

    _configure_standard_streams()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "models":
            return _run_models(args)
        if args.command == "design":
            return _run_design(args)
        parser.print_help()
        return 2
    except ValueError as exc:
        parser.error(str(exc))
    return 2


def _configure_standard_streams() -> None:
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qwen-tts")
    parser.add_argument("--config", type=Path, help="User CLI configuration JSON.")
    parser.add_argument("--portable-root", type=Path, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command")

    models = commands.add_parser("models", help="Discover, verify, or download models.")
    model_commands = models.add_subparsers(dest="models_command", required=True)
    model_commands.add_parser("list", help="List valid locally available models.")
    verify = model_commands.add_parser("verify", help="Verify one resolved model.")
    verify.add_argument("family", choices=tuple(MODEL_CATALOG), nargs="?")
    verify.add_argument("--model", type=Path)
    verify.add_argument("--native-profile")
    download = model_commands.add_parser(
        "download", help="Explicitly download a model."
    )
    download.add_argument("family", choices=tuple(MODEL_CATALOG))
    destination = download.add_mutually_exclusive_group()
    destination.add_argument("--portable", action="store_true")
    destination.add_argument("--to", type=Path)
    download.add_argument("--revision")

    design = commands.add_parser("design", help="Generate a VoiceDesign WAV.")
    design.add_argument("--text", required=True)
    design.add_argument("--instruction", required=True)
    design.add_argument("--out", type=Path, required=True)
    design.add_argument("--result-json", type=Path)
    design.add_argument("--model", type=Path)
    design.add_argument("--language", default="Russian")
    design.add_argument(
        "--runtime-backend", choices=("faster", "upstream"), default="faster"
    )
    design.add_argument("--save-wav-executable", type=Path)
    design.add_argument("--worker", type=Path)
    design.add_argument("--play", action="store_true")
    design.add_argument("--require-natural-eos", action="store_true")
    return parser


def _run_models(args: argparse.Namespace) -> int:
    root = _portable_root(args.portable_root)
    if args.models_command == "list":
        rows = list_models(
            config_path=args.config,
            portable_root=root,
        )
        for row in rows:
            revision = f" revision={row.revision}" if row.revision else ""
            print(f"{row.spec.name}\t{row.source}\t{row.path}{revision}")
        config = load_user_config(args.config)
        native_profiles = config.get("native_profiles")
        native_count = 0
        if isinstance(native_profiles, dict):
            for name in sorted(native_profiles):
                native_count += 1
                try:
                    native = resolve_native_profile(name, config_path=args.config)
                    print(f"native:{name}\tconfig\t{native.talker_model}")
                except ValueError as exc:
                    print(f"native:{name}\tinvalid\t{exc}")
        if not rows and native_count == 0:
            print("No supported models found.")
        return 0
    if args.models_command == "verify":
        if args.native_profile:
            if args.family or args.model:
                raise ValueError(
                    "--native-profile cannot be combined with a Python model"
                )
            native = resolve_native_profile(
                args.native_profile, config_path=args.config
            )
            print(
                json.dumps(
                    {
                        "profile": native.name,
                        "runtime_dir": str(native.runtime_dir),
                        "talker_model": str(native.talker_model),
                        "codec_model": str(native.codec_model),
                        "valid": True,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.family is None:
            raise ValueError("models verify requires a family or --native-profile")
        model = resolve_model(
            args.family,
            explicit_path=args.model,
            config_path=args.config,
            portable_root=root,
        )
        print(
            json.dumps(
                {
                    "family": model.spec.name,
                    "repository": model.spec.repository,
                    "path": str(model.path),
                    "source": model.source,
                    "revision": model.revision,
                    "valid": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.models_command == "download":
        if args.portable and root is None:
            raise ValueError("--portable requires an installed package root")
        model = download_model(
            args.family,
            portable_root=root if args.portable else None,
            destination=args.to,
            revision=args.revision,
        )
        print(f"Downloaded and verified {model.spec.name}: {model.path}")
        return 0
    raise ValueError("a models command is required")


def _run_design(args: argparse.Namespace) -> int:
    root = _portable_root(args.portable_root)
    model = resolve_model(
        "voice-design",
        explicit_path=args.model,
        config_path=args.config,
        portable_root=root,
    )
    config = load_user_config(args.config)
    runtime_value = config.get("runtime")
    runtime: dict[str, object] = (
        runtime_value if isinstance(runtime_value, dict) else {}
    )
    config_directory = _selected_config_path(args.config).parent
    save_wav = _resolve_executable(
        args.save_wav_executable,
        _configured_path(runtime.get("save_wav_executable"), config_directory),
        root,
        "qwen_tts_save_wav.exe",
    )
    worker = _resolve_worker(
        args.worker,
        _configured_path(runtime.get("worker"), config_directory),
        root,
    )
    result_json = args.result_json or args.out.with_suffix(args.out.suffix + ".json")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result_json.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(save_wav),
        "--worker",
        str(worker.executable),
        "--output",
        str(args.out.resolve()),
        "--result-json",
        str(result_json.resolve()),
        "--text",
        args.text,
        "--language",
        args.language,
        "--instruction",
        args.instruction,
    ]
    for value in worker.prefix_arguments:
        command.extend(("--worker-arg", value))
    for value in (
        "qwen",
        "--model-path",
        str(model.path),
        "--runtime-backend",
        args.runtime_backend,
        "--device",
        "cuda",
        "--dtype",
        "auto",
    ):
        command.extend(("--worker-arg", value))
    if args.require_natural_eos:
        command.append("--require-natural-eos")
    environment = os.environ.copy()
    if root is not None and worker.executable == Path(sys.executable).resolve():
        environment["PYTHONNOUSERSITE"] = "1"
    try:
        completed = subprocess.run(command, env=environment, check=False)
    except OSError as exc:
        raise ValueError(f"could not start {save_wav}: {exc}") from exc
    if completed.returncode != 0:
        return completed.returncode
    print(f"Wrote VoiceDesign WAV: {args.out.resolve()}")
    if args.play:
        if os.name != "nt":
            raise ValueError("--play currently requires Windows")
        try:
            os.startfile(args.out.resolve())  # type: ignore[attr-defined]
        except OSError as exc:
            raise ValueError(f"could not open generated WAV: {exc}") from exc
    return 0


class _WorkerCommand:
    def __init__(
        self, executable: Path, prefix_arguments: tuple[str, ...] = ()
    ) -> None:
        self.executable = executable
        self.prefix_arguments = prefix_arguments


def _portable_root(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve()
    value = os.environ.get("QTB_PACKAGE_ROOT")
    return Path(value).resolve() if value else None


def _selected_config_path(explicit: Path | None) -> Path:
    selected = default_user_config_path() if explicit is None else explicit
    return selected.expanduser().resolve()


def _configured_path(value: object, config_directory: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    selected = Path(value).expanduser()
    if not selected.is_absolute():
        selected = config_directory / selected
    return selected.resolve()


def _resolve_executable(
    explicit: Path | None,
    configured: Path | None,
    root: Path | None,
    name: str,
) -> Path:
    values = [explicit, configured]
    if root is not None:
        values.extend((root / name, root / "bin" / name))
    for value in values:
        if value is not None and value.expanduser().is_file():
            return value.expanduser().resolve()
    raise ValueError(
        f"{name} was not found; install it beside qwen-tts or configure its path"
    )


def _resolve_worker(
    explicit: Path | None,
    configured: Path | None,
    root: Path | None,
) -> _WorkerCommand:
    for value in (explicit, configured):
        if value is not None and value.expanduser().is_file():
            return _WorkerCommand(value.expanduser().resolve())
    if root is not None:
        python = root / "worker-python" / "python" / "python.exe"
        if python.is_file():
            return _WorkerCommand(
                python.resolve(), ("-B", "-P", "-s", "-m", "qwen_tts_bridge_worker")
            )
    return _WorkerCommand(
        Path(sys.executable).resolve(), ("-m", "qwen_tts_bridge_worker")
    )


if __name__ == "__main__":
    raise SystemExit(main())
