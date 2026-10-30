"""Release-facing QwenTTSBridge command-line interface."""

from __future__ import annotations

import argparse
import codecs
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from collections import deque
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import BinaryIO, cast

from qwen_tts_bridge_worker.model_resolver import (
    MODEL_CATALOG,
    default_user_config_path,
    download_model,
    list_models,
    load_user_config,
    resolve_model,
    resolve_native_profile,
)
from qwen_tts_bridge_worker.voice_library import (
    VoiceLibraryError,
    add_voice,
    default_voice_registry_path,
    list_voices,
    prepare_voice,
    show_voice,
    verify_voice,
)

_DEFAULT_STARTUP_TIMEOUT_MS = 120_000
_DEFAULT_REQUEST_TIMEOUT_MS = 300_000
_MAX_TIMEOUT_MS = 4_294_967_295
_DIAGNOSTIC_TAIL_BYTES = 8 * 1024
_DIAGNOSTIC_READ_CHUNK_BYTES = 4 * 1024
_DIAGNOSTIC_LINE_BYTES = 4 * 1024


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
        if args.command == "synth":
            return _run_synth(args)
        if args.command == "voices":
            return _run_voices(args)
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

    synth = commands.add_parser(
        "synth", help="Synthesize with a registered Base voice profile."
    )
    synth.add_argument("--voice-id", required=True)
    synth.add_argument("--text", required=True)
    synth.add_argument("--out", type=Path, required=True)
    synth.add_argument("--result-json", type=Path)
    synth.add_argument("--model", type=Path)
    synth.add_argument("--language", default="Russian")

    voices = commands.add_parser(
        "voices", help="Manage persistent user voice profiles."
    )
    voice_commands = voices.add_subparsers(dest="voices_command", required=True)
    add = voice_commands.add_parser("add", help="Register a reference WAV.")
    add.add_argument("--id", required=True, dest="voice_id")
    add.add_argument("--wav", required=True, type=Path)
    add.add_argument("--text", default="")
    add.add_argument("--x-vector-only", action="store_true")
    add.add_argument("--preserve-reference-text-whitespace", action="store_true")
    list_command = voice_commands.add_parser("list", help="List registered voices.")
    list_command.add_argument("--json", action="store_true")
    show = voice_commands.add_parser("show", help="Show one registered voice.")
    show.add_argument("voice_id")
    show.add_argument("--json", action="store_true")
    verify = voice_commands.add_parser("verify", help="Verify one registered voice.")
    verify.add_argument("voice_id")
    verify.add_argument("--backend", choices=("python", "native"), required=True)
    verify.add_argument("--native-profile")
    prepare = voice_commands.add_parser(
        "prepare", help="Prepare a native voice reference."
    )
    prepare.add_argument("voice_id")
    prepare.add_argument("--backend", choices=("native",), required=True)
    prepare.add_argument("--native-profile", required=True)
    prepare.add_argument("--timeout-seconds", type=float, default=300.0)
    prepare.add_argument("--json", action="store_true")
    for synthesis in (design, synth):
        synthesis.add_argument("--save-wav-executable", type=Path)
        synthesis.add_argument("--worker", type=Path)
        synthesis.add_argument(
            "--startup-timeout-ms",
            type=_parse_timeout_argument,
            help=(
                "Worker startup timeout in milliseconds "
                f"(default: {_DEFAULT_STARTUP_TIMEOUT_MS})."
            ),
        )
        synthesis.add_argument(
            "--request-timeout-ms",
            type=_parse_timeout_argument,
            help=(
                "Synthesis request timeout in milliseconds "
                f"(default: {_DEFAULT_REQUEST_TIMEOUT_MS})."
            ),
        )
        synthesis.add_argument(
            "--play",
            action="store_true",
            help=(
                "Open the completed WAV in the configured Windows default application."
            ),
        )
        synthesis.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed worker and runtime diagnostics.",
        )
        synthesis.add_argument(
            "--log-file",
            type=Path,
            help="Save complete worker and runtime diagnostics to this file.",
        )
        eos = synthesis.add_mutually_exclusive_group()
        eos.add_argument(
            "--require-natural-eos",
            dest="require_natural_eos",
            action="store_true",
            help="Require the worker to report natural EOS (the default).",
        )
        eos.add_argument(
            "--allow-non-natural-eos",
            dest="require_natural_eos",
            action="store_false",
            help="Allow a completed result without natural EOS.",
        )
        synthesis.set_defaults(require_natural_eos=True)
        synthesis.add_argument(
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
                integrity = "verified" if row.integrity_verified else "not-verified"
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


def _run_voices(args: argparse.Namespace) -> int:
    registry_path = default_voice_registry_path(args.config)
    if args.voices_command == "add":
        row = add_voice(
            registry_path,
            voice_id=args.voice_id,
            wav_path=args.wav,
            reference_text=args.text,
            x_vector_only=args.x_vector_only,
            preserve_reference_text_whitespace=args.preserve_reference_text_whitespace,
        )
        print(
            json.dumps(
                {
                    "status": "registered",
                    "registry_path": str(registry_path),
                    "voice": row,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.voices_command == "list":
        rows = list_voices(registry_path)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, sort_keys=True))
        else:
            for row in rows:
                print(
                    f"{row['voice_id']}\tpython={row['python_status']}\tnative={row['native_status']}"
                )
            if not rows:
                print("No voices registered.")
        return 0
    if args.voices_command == "show":
        value = show_voice(registry_path, args.voice_id)
        print(
            json.dumps(value, ensure_ascii=False, sort_keys=True)
            if args.json
            else json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        )
        return 0
    if args.voices_command == "verify":
        value = verify_voice(
            registry_path,
            args.voice_id,
            backend=args.backend,
            native_profile=args.native_profile,
            config_path=args.config,
        )
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return 0 if value.get("status") in {"compatible", "prepared_valid"} else 1
    if args.voices_command == "prepare":
        value = prepare_voice(
            registry_path,
            args.voice_id,
            native_profile=args.native_profile,
            config_path=args.config,
            timeout_seconds=args.timeout_seconds,
        )
        print(
            json.dumps(value, ensure_ascii=False, sort_keys=True)
            if args.json
            else f"Prepared native voice {args.voice_id} ({args.native_profile})."
        )
        return 0
    raise VoiceLibraryError("a voices command is required")


def _run_design(args: argparse.Namespace) -> int:
    root = _portable_root(args.portable_root)
    model = resolve_model(
        "voice-design",
        explicit_path=args.model,
        config_path=args.config,
        portable_root=root,
    )
    worker_arguments = (
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
    if args.runtime_backend == "faster":
        worker_arguments += ("--collect-generation-trace",)
    return _run_synthesis(
        args,
        root=root,
        worker_arguments=worker_arguments,
        request_arguments=("--instruction", args.instruction),
        output_description="VoiceDesign WAV",
    )


def _run_synth(args: argparse.Namespace) -> int:
    root = _portable_root(args.portable_root)
    registry_path = default_voice_registry_path(args.config).expanduser().resolve()
    verification = verify_voice(
        registry_path,
        args.voice_id,
        backend="python",
        config_path=args.config,
    )
    if verification.get("status") != "compatible":
        detail = verification.get("error")
        suffix = f": {detail}" if isinstance(detail, str) and detail else ""
        raise VoiceLibraryError(
            f"voice {args.voice_id} is not compatible with the Python backend{suffix}"
        )
    model = resolve_model(
        "base-1.7b",
        explicit_path=args.model,
        config_path=args.config,
        portable_root=root,
    )
    worker_arguments = (
        "qwen",
        "--model-path",
        str(model.path),
        "--runtime-backend",
        "faster",
        "--device",
        "cuda",
        "--dtype",
        "auto",
        "--collect-generation-trace",
        "--voice-registry-path",
        str(registry_path),
    )
    return _run_synthesis(
        args,
        root=root,
        worker_arguments=worker_arguments,
        request_arguments=("--voice-id", args.voice_id),
        output_description="Base voice WAV",
    )


def _run_synthesis(
    args: argparse.Namespace,
    *,
    root: Path | None,
    worker_arguments: tuple[str, ...],
    request_arguments: tuple[str, ...],
    output_description: str,
) -> int:
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
    output_path = _output_path(args.out)
    result_json = _output_path(result_json)
    log_file = (
        _output_path(args.log_file) if getattr(args, "log_file", None) else None
    )
    if output_path == result_json:
        raise ValueError("--out and --result-json must refer to different files")
    if log_file is not None and log_file in (output_path, result_json):
        raise ValueError("--log-file must be different from synthesis outputs")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_json.parent.mkdir(parents=True, exist_ok=True)
    _reject_output_target(output_path)
    _reject_output_target(result_json)
    startup_timeout_ms = _resolve_timeout(
        args.startup_timeout_ms,
        runtime.get("startup_timeout_ms"),
        "runtime.startup_timeout_ms",
        _DEFAULT_STARTUP_TIMEOUT_MS,
    )
    request_timeout_ms = _resolve_timeout(
        args.request_timeout_ms,
        runtime.get("request_timeout_ms"),
        "runtime.request_timeout_ms",
        _DEFAULT_REQUEST_TIMEOUT_MS,
    )
    try:
        temporary_outputs = _temporary_output_paths(output_path, result_json)
    except OSError as exc:
        raise ValueError(
            f"could not create temporary synthesis outputs: {exc}"
        ) from exc
    temporary_wav, temporary_result = temporary_outputs

    command = [
        str(save_wav),
        "--worker",
        str(worker.executable),
        "--output",
        str(temporary_wav),
        "--result-json",
        str(temporary_result),
        "--startup-timeout-ms",
        str(startup_timeout_ms),
        "--request-timeout-ms",
        str(request_timeout_ms),
        "--text",
        args.text,
        "--language",
        args.language,
    ]
    command.extend(request_arguments)
    for value in worker.prefix_arguments:
        command.extend(("--worker-arg", value))
    if args.acceptance_mock_worker:
        worker_arguments = ("mock", "--chunks", "2", "--chunk-ms", "40")
    for value in worker_arguments:
        command.extend(("--worker-arg", value))
    if args.require_natural_eos:
        command.append("--require-natural-eos")
    environment = os.environ.copy()
    if root is not None and worker.executable == Path(sys.executable).resolve():
        environment["PYTHONNOUSERSITE"] = "1"
    diagnostics = cast(BinaryIO, tempfile.TemporaryFile(mode="w+b"))
    try:
        try:
            completed = subprocess.run(
                command,
                env=environment,
                check=False,
                stdout=diagnostics,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            raise ValueError(f"could not start {save_wav}: {exc}") from exc
        diagnostics.flush()
        if log_file is not None:
            _write_diagnostic_log(diagnostics, log_file)
        if args.verbose:
            _emit_diagnostics(diagnostics)
        if completed.returncode != 0:
            if not args.verbose:
                _emit_failure_diagnostics(completed.returncode, diagnostics)
            else:
                print(
                    f"Synthesis failed (exit code {completed.returncode}).",
                    file=sys.stderr,
                )
            return completed.returncode
        _validate_design_outputs(
            temporary_wav, temporary_result, args.require_natural_eos
        )
        _publish_design_outputs(
            temporary_wav,
            temporary_result,
            output_path,
            result_json,
        )
    finally:
        diagnostics.close()
        for temporary_path in temporary_outputs:
            _remove_owned_temporary(temporary_path)
    print(f"Wrote {output_description}: {output_path}")
    if args.play:
        if os.name != "nt":
            raise ValueError("--play currently requires Windows")
        try:
            os.startfile(output_path)  # type: ignore[attr-defined]
        except OSError as exc:
            raise ValueError(f"could not open generated WAV: {exc}") from exc
    return 0


def _write_diagnostic_log(stream: BinaryIO, path: Path) -> None:
    """Atomically replace a requested diagnostic log without buffering it all."""

    _reject_output_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".qtb-log-tmp", dir=path.parent
        )
        with os.fdopen(descriptor, "w+b") as destination:
            stream.seek(0)
            shutil.copyfileobj(stream, destination)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    except OSError as exc:
        raise ValueError(f"could not write diagnostic log {path}: {exc}") from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def _emit_diagnostics(stream: BinaryIO) -> None:
    stream.seek(0)
    wrote = False
    last_character = ""
    for text in _iter_decoded_diagnostic_chunks(stream):
        wrote = True
        last_character = text[-1]
        sys.stderr.write(text)
    if wrote and last_character != "\n":
        sys.stderr.write("\n")
    if wrote:
        sys.stderr.flush()


def _emit_failure_diagnostics(returncode: int, stream: BinaryIO) -> None:
    print(f"Synthesis failed (exit code {returncode}).", file=sys.stderr)
    text = _collect_failure_diagnostics(stream)
    if text:
        print("Diagnostic tail:", file=sys.stderr)
        print(text, file=sys.stderr)


def _iter_decoded_diagnostic_chunks(stream: BinaryIO) -> Iterator[str]:
    """Yield decoded diagnostics in bounded chunks without retaining the log."""

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while True:
        chunk = stream.read(_DIAGNOSTIC_READ_CHUNK_BYTES)
        if not chunk:
            break
        text = decoder.decode(chunk, final=False)
        if text:
            yield text
    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail


def _iter_diagnostic_lines(stream: BinaryIO) -> Iterator[tuple[bytes, bool]]:
    """Yield bounded raw lines and whether each line exceeded the cap."""

    line = bytearray()
    truncated = False
    while True:
        chunk = stream.read(_DIAGNOSTIC_READ_CHUNK_BYTES)
        if not chunk:
            break
        for value in chunk:
            if value == ord("\n"):
                yield bytes(line), truncated
                line.clear()
                truncated = False
            elif not truncated:
                if len(line) < _DIAGNOSTIC_LINE_BYTES:
                    line.append(value)
                else:
                    truncated = True
    if line or truncated:
        yield bytes(line), truncated


def _collect_failure_diagnostics(stream: BinaryIO) -> str:
    """Keep a bounded tail of recent non-metric diagnostic lines."""

    stream.seek(0)
    entries: deque[tuple[str, int]] = deque()
    total_bytes = 0
    for raw_line, truncated in _iter_diagnostic_lines(stream):
        if raw_line.startswith(b"qtb_metric "):
            continue
        raw_line = raw_line.rstrip(b"\r")
        text = raw_line.decode("utf-8", errors="replace")
        if truncated:
            text += " …[line truncated]"
        if not text:
            continue
        encoded_size = len(text.encode("utf-8")) + 1
        if encoded_size > _DIAGNOSTIC_TAIL_BYTES:
            text = text[-(_DIAGNOSTIC_TAIL_BYTES - 32) :]
            text = "…[line truncated] " + text
            encoded_size = len(text.encode("utf-8")) + 1
        entries.append((text, encoded_size))
        total_bytes += encoded_size
        while total_bytes > _DIAGNOSTIC_TAIL_BYTES and entries:
            _, removed_size = entries.popleft()
            total_bytes -= removed_size
    return "\n".join(text for text, _ in entries)


def _parse_timeout_argument(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "timeout must be a positive integer number of milliseconds"
        ) from exc
    try:
        return _validate_timeout(parsed, "timeout")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _validate_timeout(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of milliseconds")
    if value <= 0 or value > _MAX_TIMEOUT_MS:
        raise ValueError(f"{name} must be between 1 and {_MAX_TIMEOUT_MS} milliseconds")
    return value


def _resolve_timeout(
    explicit: int | None,
    configured: object,
    name: str,
    default: int,
) -> int:
    if explicit is not None:
        return _validate_timeout(explicit, name)
    if configured is None:
        return default
    return _validate_timeout(configured, name)


def _output_path(path: Path) -> Path:
    return Path(path.expanduser()).absolute()


def _reject_output_target(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing to overwrite symlink output: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"refusing to overwrite non-file output: {path}")


def _temporary_output_paths(output_path: Path, result_json: Path) -> tuple[Path, Path]:
    paths: list[Path] = []
    try:
        for target in (output_path, result_json):
            descriptor, name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".qtb-tmp", dir=target.parent
            )
            os.close(descriptor)
            paths.append(Path(name))
        return paths[0], paths[1]
    except OSError:
        for path in paths:
            _remove_owned_temporary(path)
        raise


def _remove_owned_temporary(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _publish_design_outputs(
    temporary_wav: Path,
    temporary_result: Path,
    output_path: Path,
    result_json: Path,
) -> None:
    targets = ((temporary_wav, output_path), (temporary_result, result_json))
    backups: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for _, target in targets:
            _reject_output_target(target)
        for _, target in targets:
            if target.exists():
                backup = _temporary_backup_path(target)
                os.replace(target, backup)
                backups.append((target, backup))
        for temporary, target in targets:
            os.replace(temporary, target)
            published.append(target)
    except OSError as exc:
        for target in published:
            _remove_owned_temporary(target)
        rollback_errors: list[str] = []
        for target, backup in reversed(backups):
            try:
                os.replace(backup, target)
            except OSError as rollback_exc:
                rollback_errors.append(
                    f"original {target} remains at backup {backup}: {rollback_exc}"
                )
        if rollback_errors:
            detail = "; ".join(rollback_errors)
            raise ValueError(
                "could not publish generated VoiceDesign outputs and rollback "
                f"was incomplete ({detail})"
            ) from exc
        raise ValueError(
            f"could not publish generated VoiceDesign outputs: {exc}"
        ) from exc
    else:
        for _, backup in backups:
            _remove_owned_temporary(backup)


def _temporary_backup_path(target: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".qtb-backup", dir=target.parent
    )
    os.close(descriptor)
    backup = Path(name)
    backup.unlink()
    return backup


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
        or receipt.get("generation_trace_available") is not True
        or receipt.get("termination_reason") != "eos"
        or receipt.get("hit_eos") is not True
        or receipt.get("hit_max_seq_len") is not False
        or receipt.get("hit_max_new_tokens") is not False
    ):
        raise ValueError("result JSON does not confirm natural EOS")


if __name__ == "__main__":
    raise SystemExit(main())
