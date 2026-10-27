"""Release-facing QwenTTSBridge command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import wave
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
    list_command = model_commands.add_parser(
        "list", help="List locally available models, including invalid candidates."
    )
    list_command.add_argument("--json", action="store_true")
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
    design.add_argument(
        "--play",
        action="store_true",
        help="Open the completed WAV in the configured Windows default application.",
    )
    design.add_argument("--require-natural-eos", action="store_true")
    design.add_argument(
        "--acceptance-mock-worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def _run_models(args: argparse.Namespace) -> int:
    root = _portable_root(args.portable_root)
    if args.models_command == "list":
        rows = list_models(
            config_path=args.config,
            portable_root=root,
        )
        output_rows: list[dict[str, object]] = []
        for row in rows:
            output_rows.append(
                {
                    "family": row.spec.name,
                    "source": row.source,
                    "path": str(row.path) if row.path is not None else None,
                    "revision": row.revision,
                    "structurally_valid": row.structurally_valid,
                    "integrity_verified": row.integrity_verified,
                    "error": row.error,
                }
            )
            if not args.json:
                revision = f" revision={row.revision}" if row.revision else ""
                status = "valid" if row.structurally_valid else "invalid"
                integrity = (
                    "verified" if row.integrity_verified else "not-verified"
                )
                detail = row.error or str(row.path)
                print(
                    f"{row.spec.name}\t{row.source}\t{status}\t{detail}"
                    f"{revision} integrity={integrity}"
                )
        config = load_user_config(args.config)
        native_profiles = config.get("native_profiles")
        native_count = 0
        if isinstance(native_profiles, dict):
            for name in sorted(native_profiles):
                native_count += 1
                try:
                    native = resolve_native_profile(name, config_path=args.config)
                    output_rows.append(
                        {
                            "family": f"native:{name}",
                            "source": "config",
                            "path": str(native.talker_model),
                            "structurally_valid": True,
                            "integrity_verified": False,
                            "error": None,
                        }
                    )
                    if not args.json:
                        print(f"native:{name}\tconfig\tvalid\t{native.talker_model}")
                except ValueError as exc:
                    output_rows.append(
                        {
                            "family": f"native:{name}",
                            "source": "config",
                            "path": None,
                            "structurally_valid": False,
                            "integrity_verified": False,
                            "error": str(exc),
                        }
                    )
                    if not args.json:
                        print(f"native:{name}\tconfig\tinvalid\t{exc}")
        if args.json:
            print(json.dumps(output_rows, ensure_ascii=False, sort_keys=True))
        elif not rows and native_count == 0:
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
                    "structurally_valid": True,
                    "integrity_verified": model.integrity_verified,
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
        integrity = "verified" if model.integrity_verified else "not verified"
        print(
            f"Downloaded and structurally validated {model.spec.name}: "
            f"{model.path} (integrity {integrity})"
        )
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
    output_path = args.out.expanduser().resolve()
    result_json = result_json.expanduser().resolve()
    if output_path == result_json:
        raise ValueError("--out and --result-json must refer to different files")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_json.parent.mkdir(parents=True, exist_ok=True)
    for stale_path in (output_path, result_json):
        if stale_path.exists():
            stale_path.unlink()

    command = [
        str(save_wav),
        "--worker",
        str(worker.executable),
        "--output",
        str(output_path),
        "--result-json",
        str(result_json),
        "--text",
        args.text,
        "--language",
        args.language,
        "--instruction",
        args.instruction,
    ]
    for value in worker.prefix_arguments:
        command.extend(("--worker-arg", value))
    worker_arguments = (
        ("mock", "--chunks", "2", "--chunk-ms", "40")
        if args.acceptance_mock_worker
        else (
            "qwen",
            "--model-path",
            str(model.path),
            "--runtime-backend",
            args.runtime_backend,
            "--device",
            "cuda",
            "--dtype",
            "auto",
        )
    )
    for value in worker_arguments:
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
    _validate_design_outputs(output_path, result_json, args.require_natural_eos)
    print(f"Wrote VoiceDesign WAV: {output_path}")
    if args.play:
        if os.name != "nt":
            raise ValueError("--play currently requires Windows")
        try:
            os.startfile(output_path)  # type: ignore[attr-defined]
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
    if explicit is not None:
        selected = explicit.expanduser().resolve()
        if not selected.is_file():
            raise ValueError(f"explicit {name} was not found: {selected}")
        return selected
    if configured is not None:
        selected = configured.expanduser().resolve()
        if not selected.is_file():
            raise ValueError(f"configured {name} was not found: {selected}")
        return selected
    values: list[Path] = []
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
    if explicit is not None:
        selected = explicit.expanduser().resolve()
        if not selected.is_file():
            raise ValueError(f"explicit worker executable was not found: {selected}")
        return _WorkerCommand(selected)
    if configured is not None:
        selected = configured.expanduser().resolve()
        if not selected.is_file():
            raise ValueError(f"configured worker executable was not found: {selected}")
        return _WorkerCommand(selected)
    if root is not None:
        python = root / "worker-python" / "python" / "python.exe"
        if python.is_file():
            return _WorkerCommand(
                python.resolve(), ("-B", "-P", "-s", "-m", "qwen_tts_bridge_worker")
            )
        raise ValueError(
            f"portable worker executable was not found: {python.resolve()}"
        )
    return _WorkerCommand(
        Path(sys.executable).resolve(), ("-m", "qwen_tts_bridge_worker")
    )


def _validate_design_outputs(
    output_path: Path,
    result_json: Path,
    require_natural_eos: bool,
) -> None:
    if not output_path.is_file():
        raise ValueError(
            f"synthesis reported success but WAV was not created: {output_path}"
        )
    try:
        with wave.open(str(output_path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            compression = wav.getcomptype()
    except (OSError, EOFError, wave.Error) as exc:
        raise ValueError(
            f"generated WAV is not a valid PCM WAVE file: {output_path}"
        ) from exc
    if (
        channels != 1
        or sample_width != 2
        or sample_rate != 24000
        or frame_count <= 0
        or compression != "NONE"
    ):
        raise ValueError(
            "generated WAV must contain non-empty 24 kHz mono s16le PCM audio"
        )

    try:
        receipt = json.loads(result_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "synthesis reported success but result JSON is missing or invalid: "
            f"{result_json}"
        ) from exc
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        raise ValueError("result JSON must be a schema_version 1 object")
    audio_bytes = receipt.get("audio_bytes")
    audio_chunks = receipt.get("audio_chunks")
    expected_audio_bytes = frame_count * channels * sample_width
    if (
        receipt.get("terminal_state") != "completed"
        or not isinstance(audio_chunks, int)
        or audio_chunks <= 0
        or audio_bytes != expected_audio_bytes
    ):
        raise ValueError("result JSON is inconsistent with the generated WAV")
    if require_natural_eos and (
        receipt.get("completion_metadata_received") is not True
        or receipt.get("termination_reason") != "eos"
        or receipt.get("hit_eos") is not True
        or receipt.get("hit_max_seq_len") is not False
        or receipt.get("hit_max_new_tokens") is not False
    ):
        raise ValueError("result JSON does not confirm natural EOS")


if __name__ == "__main__":
    raise SystemExit(main())
