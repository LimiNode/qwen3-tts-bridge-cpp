"""Authoritative model discovery and validation for the user-facing CLI."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

ModelFamily = Literal["voice-design", "base-1.7b", "base-0.6b"]


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Describe one supported Hugging Face model identity."""

    name: ModelFamily
    repository: str
    model_type: str
    model_size: str

    @property
    def directory_name(self) -> str:
        return self.repository.rsplit("/", 1)[-1]


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    """A validated local model selected from one discovery source."""

    spec: ModelSpec
    path: Path
    source: str
    revision: str | None = None
    integrity_verified: bool = False


@dataclass(frozen=True, slots=True)
class ModelDiagnostic:
    """Describe one valid or invalid model selected by discovery precedence."""

    spec: ModelSpec
    path: Path | None
    source: str
    revision: str | None
    structurally_valid: bool
    integrity_verified: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedNativeProfile:
    """Validated native GGUF profile with explicit runtime dependencies."""

    name: str
    runtime_dir: Path
    talker_model: Path
    codec_model: Path


MODEL_CATALOG: dict[str, ModelSpec] = {
    "voice-design": ModelSpec(
        "voice-design",
        "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "voice_design",
        "1b7",
    ),
    "base-1.7b": ModelSpec(
        "base-1.7b",
        "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "base",
        "1b7",
    ),
    "base-0.6b": ModelSpec(
        "base-0.6b",
        "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "base",
        "0b6",
    ),
}

_REQUIRED_FILES = (
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
    "speech_tokenizer/config.json",
    "speech_tokenizer/model.safetensors",
    "speech_tokenizer/preprocessor_config.json",
)
_TRANSIENT_SUFFIXES = (".incomplete", ".lock", ".partial", ".tmp")


def default_user_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the per-user CLI config path without creating it."""

    env = os.environ if environ is None else environ
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "QwenTTSBridge" / "config.json"
    return Path.home() / ".config" / "qwen-tts-bridge" / "config.json"


def hugging_face_cache_root(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the Hugging Face hub cache using documented precedence."""

    env = os.environ if environ is None else environ
    if env.get("HF_HUB_CACHE"):
        return Path(env["HF_HUB_CACHE"]).expanduser()
    if env.get("HF_HOME"):
        return Path(env["HF_HOME"]).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def load_user_config(
    path: Path | None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Load an optional schema-1 user config."""

    selected = default_user_config_path(environ) if path is None else path
    selected = selected.expanduser().resolve()
    if not selected.is_file():
        return {}
    try:
        value = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"CLI config is not valid UTF-8 JSON: {selected}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError(f"CLI config must be a schema_version 1 object: {selected}")
    return value


def resolve_model(
    family: str,
    *,
    explicit_path: Path | None = None,
    config_path: Path | None = None,
    portable_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ResolvedModel:
    """Resolve and validate a Python checkpoint using fixed precedence."""

    spec = model_spec(family)
    if explicit_path is not None:
        path = explicit_path.expanduser().resolve()
        integrity_verified = validate_python_model(path, spec)
        return ResolvedModel(spec, path, "explicit", None, integrity_verified)

    selected_config_path = (
        (default_user_config_path(environ) if config_path is None else config_path)
        .expanduser()
        .resolve()
    )
    config = load_user_config(selected_config_path, environ)
    configured = _configured_model(config, spec, selected_config_path.parent)
    if configured is not None:
        path, revision = configured
        integrity_verified = validate_python_model(path, spec)
        return ResolvedModel(spec, path, "config", revision, integrity_verified)

    if portable_root is not None:
        portable = portable_root.resolve() / "models" / spec.directory_name
        if portable.exists():
            integrity_verified = validate_python_model(portable, spec)
            return ResolvedModel(
                spec, portable, "portable", None, integrity_verified
            )

    cache_root = hugging_face_cache_root(environ)
    snapshot, revision = resolve_hf_snapshot(cache_root, spec.repository)
    if snapshot is not None:
        integrity_verified = validate_python_model(snapshot, spec)
        return ResolvedModel(
            spec, snapshot, "huggingface-cache", revision, integrity_verified
        )

    raise ValueError(
        f"{spec.name} model was not found. Install it explicitly with: "
        f"qwen-tts models download {spec.name}"
    )


def resolve_hf_snapshot(
    cache_root: Path,
    repository: str,
    revision: str | None = None,
) -> tuple[Path | None, str | None]:
    """Resolve one complete HF snapshot without guessing among revisions."""

    repo_root = cache_root / ("models--" + repository.replace("/", "--"))
    snapshots = repo_root / "snapshots"
    if not snapshots.is_dir():
        return None, None

    requested = revision
    if requested is None:
        main_ref = repo_root / "refs" / "main"
        if main_ref.is_file():
            requested = main_ref.read_text(encoding="utf-8").strip()
    if requested:
        direct = snapshots / requested
        if direct.is_dir() and not _has_transient_files(direct):
            return direct.resolve(), requested
        ref = repo_root / "refs" / requested
        if ref.is_file():
            commit = ref.read_text(encoding="utf-8").strip()
            candidate = snapshots / commit
            if candidate.is_dir() and not _has_transient_files(candidate):
                return candidate.resolve(), commit
        return None, None

    candidates = sorted(
        path
        for path in snapshots.iterdir()
        if path.is_dir() and not _has_transient_files(path)
    )
    if len(candidates) > 1:
        raise ValueError(
            f"multiple cached revisions exist for {repository}; "
            "configure an exact revision"
        )
    if len(candidates) == 1:
        return candidates[0].resolve(), candidates[0].name
    return None, None


def validate_python_model(path: Path, spec: ModelSpec) -> bool:
    """Validate a checkpoint and report complete-manifest integrity status."""

    if not path.is_dir():
        raise ValueError(f"model path is not a directory: {path}")
    if _has_transient_files(path):
        raise ValueError(f"model contains incomplete download artifacts: {path}")
    missing = [name for name in _REQUIRED_FILES if not (path / name).is_file()]
    if missing:
        raise ValueError("model is incomplete; missing: " + ", ".join(missing))
    config = _read_json(path / "config.json")
    if config.get("model_type") != "qwen3_tts":
        raise ValueError("model config is not a Qwen3-TTS checkpoint")
    actual_type = config.get("tts_model_type")
    if actual_type != spec.model_type:
        raise ValueError(
            f"model family mismatch: expected {spec.model_type}, found "
            f"{actual_type or 'unknown'}"
        )
    actual_size = config.get("tts_model_size")
    if actual_size != spec.model_size:
        raise ValueError(
            f"model size mismatch: expected {spec.model_size}, found "
            f"{actual_size or 'unknown'}"
        )
    manifest_path = path / "model-runtime-manifest.json"
    if manifest_path.is_file():
        return _verify_manifest(path, _read_json(manifest_path))
    return False


def list_models(
    *,
    config_path: Path | None = None,
    portable_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[ModelDiagnostic]:
    """List catalog models, preserving diagnostics for invalid candidates."""

    found: list[ModelDiagnostic] = []
    for name in MODEL_CATALOG:
        try:
            model = resolve_model(
                name,
                config_path=config_path,
                portable_root=portable_root,
                environ=environ,
            )
            found.append(
                ModelDiagnostic(
                    model.spec,
                    model.path,
                    model.source,
                    model.revision,
                    True,
                    model.integrity_verified,
                )
            )
        except ValueError as exc:
            candidate = _selected_candidate(
                MODEL_CATALOG[name], config_path, portable_root, environ
            )
            if candidate is None:
                continue
            path, source, revision = candidate
            found.append(
                ModelDiagnostic(
                    MODEL_CATALOG[name],
                    path,
                    source,
                    revision,
                    False,
                    False,
                    str(exc),
                )
            )
    return found


def download_model(
    family: str,
    *,
    portable_root: Path | None = None,
    destination: Path | None = None,
    revision: str | None = None,
    cache_root: Path | None = None,
    downloader: Callable[..., str] | None = None,
) -> ResolvedModel:
    """Explicitly provision a model through huggingface_hub."""

    spec = model_spec(family)
    if portable_root is not None and destination is not None:
        raise ValueError("--portable and --to are mutually exclusive")
    selected_downloader = downloader
    if selected_downloader is None:
        try:
            module = importlib.import_module("huggingface_hub")
        except ModuleNotFoundError as exc:
            raise ValueError(
                "huggingface_hub is required for downloads; "
                "install the packaged Qwen runtime"
            ) from exc
        candidate = getattr(module, "snapshot_download", None)
        if not callable(candidate):
            raise ValueError("huggingface_hub does not provide snapshot_download")
        selected_downloader = cast(Callable[..., str], candidate)

    if portable_root is None and destination is None:
        path = Path(
            selected_downloader(
                repo_id=spec.repository,
                revision=revision,
                cache_dir=str(cache_root) if cache_root else None,
            )
        ).resolve()
        integrity_verified = validate_python_model(path, spec)
        resolved_revision = revision or _snapshot_revision(path)
        return ResolvedModel(
            spec,
            path,
            "huggingface-cache",
            resolved_revision,
            integrity_verified,
        )

    target = (
        portable_root.resolve() / "models" / spec.directory_name
        if portable_root is not None
        else destination.expanduser().resolve() / spec.directory_name  # type: ignore[union-attr]
    )
    if target.exists():
        raise ValueError(f"download target already exists: {target}")
    _assert_writable_parent(target.parent)
    staging = target.parent / f".{target.name}.incomplete"
    if staging.exists():
        raise ValueError(f"incomplete download staging path already exists: {staging}")
    try:
        selected_downloader(
            repo_id=spec.repository,
            revision=revision,
            local_dir=str(staging),
        )
        integrity_verified = validate_python_model(staging, spec)
        _remove_hugging_face_metadata(staging)
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return ResolvedModel(
        spec,
        target,
        "portable" if portable_root else "explicit",
        revision,
        integrity_verified,
    )


def resolve_native_profile(
    name: str,
    *,
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ResolvedNativeProfile:
    """Resolve an explicit native profile without applying HF layout rules."""

    selected_config = (
        (default_user_config_path(environ) if config_path is None else config_path)
        .expanduser()
        .resolve()
    )
    config = load_user_config(selected_config, environ)
    profiles = config.get("native_profiles")
    if not isinstance(profiles, dict) or not isinstance(profiles.get(name), dict):
        raise ValueError(f"native model profile was not found: {name}")
    entry = profiles[name]
    assert isinstance(entry, dict)
    base = selected_config.expanduser().resolve().parent

    def required_path(field: str, *, directory: bool = False) -> Path:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"native profile {name} must define {field}")
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve()
        valid = path.is_dir() if directory else path.is_file()
        if not valid:
            raise ValueError(f"native profile {field} was not found: {path}")
        return path

    runtime = required_path("runtime_dir", directory=True)
    talker = required_path("talker_model")
    codec = required_path("codec_model")
    _verify_optional_sha(talker, entry.get("talker_sha256"), "talker_model")
    _verify_optional_sha(codec, entry.get("codec_sha256"), "codec_model")
    if not (runtime / "qwen.dll").is_file():
        raise ValueError(f"native profile runtime has no qwen.dll: {runtime}")
    return ResolvedNativeProfile(name, runtime, talker, codec)


def model_spec(family: str) -> ModelSpec:
    """Return a supported catalog entry or an actionable error."""

    try:
        return MODEL_CATALOG[family]
    except KeyError as exc:
        raise ValueError(
            f"unknown model family '{family}'; choose: {', '.join(MODEL_CATALOG)}"
        ) from exc


def _configured_model(
    config: dict[str, object], spec: ModelSpec, config_directory: Path
) -> tuple[Path, str | None] | None:
    models = config.get("models")
    if not isinstance(models, dict):
        return None
    entry = models.get(spec.name)
    if not isinstance(entry, dict):
        return None
    path = entry.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    revision = entry.get("revision")
    if revision is not None and not isinstance(revision, str):
        raise ValueError(f"configured revision for {spec.name} must be a string")
    selected = Path(path).expanduser()
    if not selected.is_absolute():
        selected = config_directory / selected
    return selected.resolve(), revision


def _has_transient_files(root: Path) -> bool:
    return any(
        path.is_file()
        and not _is_hugging_face_metadata(path, root)
        and path.name.endswith(_TRANSIENT_SUFFIXES)
        for path in root.rglob("*")
    )


def _is_hugging_face_metadata(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return relative.parts[:2] == (".cache", "huggingface")


def _remove_hugging_face_metadata(root: Path) -> None:
    """Remove downloader bookkeeping before promoting a completed snapshot."""

    metadata_root = root / ".cache" / "huggingface"
    if metadata_root.is_dir():
        shutil.rmtree(metadata_root)
        cache_root = metadata_root.parent
        if cache_root.is_dir() and not any(cache_root.iterdir()):
            cache_root.rmdir()


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"file is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return value


def _verify_manifest(root: Path, manifest: dict[str, object]) -> bool:
    files = manifest.get("runtime_files")
    if not isinstance(files, list) or not files:
        raise ValueError("model manifest has no runtime_files")
    expected_paths: set[str] = set()
    complete_entries = True
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("model manifest file entry is invalid")
        name = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError("model manifest file entry is invalid")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name in expected_paths:
            raise ValueError("model manifest path is unsafe")
        expected_paths.add(name)
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise ValueError("model manifest path is unsafe")
        if not _is_sha256(digest):
            raise ValueError(f"model manifest SHA-256 is invalid: {name}")
        if not candidate.is_file() or _sha256_file(candidate) != digest.lower():
            raise ValueError(f"model manifest integrity failed: {name}")
        expected_size = entry.get("size_bytes")
        if not isinstance(expected_size, int) or expected_size < 0:
            complete_entries = False
        elif candidate.stat().st_size != expected_size:
            raise ValueError(f"model manifest size failed: {name}")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "model-runtime-manifest.json"
        and not _is_hugging_face_metadata(path, root)
    }
    complete = complete_entries and actual_paths == expected_paths
    schema = manifest.get("model_runtime_manifest_schema_version")
    directory_hash = manifest.get("directory_manifest_sha256")
    if schema == 1 or directory_hash is not None:
        unsigned = dict(manifest)
        unsigned.pop("directory_manifest_sha256", None)
        expected_hash = hashlib.sha256(
            (
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
        ).hexdigest()
        if (
            not isinstance(directory_hash, str)
            or directory_hash.lower() != expected_hash
        ):
            raise ValueError("model manifest SHA-256 is invalid")
        complete = complete and schema == 1
    else:
        complete = False
    return complete


def _selected_candidate(
    spec: ModelSpec,
    config_path: Path | None,
    portable_root: Path | None,
    environ: Mapping[str, str] | None,
) -> tuple[Path, str, str | None] | None:
    selected_config = (
        (default_user_config_path(environ) if config_path is None else config_path)
        .expanduser()
        .resolve()
    )
    try:
        configured = _configured_model(
            load_user_config(selected_config, environ), spec, selected_config.parent
        )
    except ValueError:
        return selected_config, "config", None
    if configured is not None:
        return configured[0], "config", configured[1]
    if portable_root is not None:
        portable = portable_root.resolve() / "models" / spec.directory_name
        if portable.exists():
            return portable, "portable", None
    cache_root = hugging_face_cache_root(environ)
    repo_root = cache_root / ("models--" + spec.repository.replace("/", "--"))
    snapshots = repo_root / "snapshots"
    if not snapshots.is_dir():
        return None
    main_ref = repo_root / "refs" / "main"
    if main_ref.is_file():
        revision = main_ref.read_text(encoding="utf-8").strip()
        candidate = snapshots / revision
        if candidate.exists():
            return candidate.resolve(), "huggingface-cache", revision
    candidates = sorted(path for path in snapshots.iterdir() if path.is_dir())
    if len(candidates) == 1:
        return candidates[0].resolve(), "huggingface-cache", candidates[0].name
    if candidates:
        return snapshots.resolve(), "huggingface-cache", None
    return None


def _snapshot_revision(path: Path) -> str | None:
    return path.name if path.parent.name == "snapshots" else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_optional_sha(path: Path, expected: object, field: str) -> None:
    if expected is None:
        return
    if not isinstance(expected, str) or not _is_sha256(expected):
        raise ValueError(f"native profile {field} SHA-256 is invalid")
    if _sha256_file(path) != expected.lower():
        raise ValueError(f"native profile {field} SHA-256 does not match")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


def _assert_writable_parent(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        descriptor, probe = tempfile.mkstemp(prefix=".qtb-write-test-", dir=path)
        os.close(descriptor)
        Path(probe).unlink()
    except OSError as exc:
        raise ValueError(f"download destination is not writable: {path}") from exc
