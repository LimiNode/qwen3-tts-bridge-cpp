"""Runtime fingerprint helpers for local benchmark JSON artifacts."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DISTRIBUTION_BY_MODULE = {
    "torch": "torch",
    "faster_qwen3_tts": "faster-qwen3-tts",
    "qwen_tts": "qwen-tts",
    "qwen_tts_bridge_worker": "qwen-tts-bridge-worker",
}


def runtime_fingerprint(
    *,
    worker_executable: Path,
    worker_prefix_args: list[str],
    args: Any,
) -> dict[str, object]:
    """Collect best-effort runtime metadata for benchmark provenance."""

    return {
        "host": _host_info(),
        "python": _python_info(),
        "packages": _package_versions(
            [
                "torch",
                "transformers",
                "faster-qwen3-tts",
                "qwen-tts",
                "qwen-tts-bridge-worker",
            ]
        ),
        "imports": _import_provenance(
            [
                "torch",
                "faster_qwen3_tts",
                "qwen_tts",
                "qwen_tts_bridge_worker",
            ]
        ),
        "torch": _torch_info(),
        "git": _git_info(_REPO_ROOT),
        "worker": _worker_info(worker_executable, worker_prefix_args),
        "qwen": _qwen_config(args),
        "gpu": gpu_snapshot(),
        "process": process_placement(),
    }


def gpu_snapshot() -> dict[str, object]:
    """Return a compact NVIDIA GPU state snapshot when nvidia-smi is available."""

    fields = [
        "driver_version",
        "pstate",
        "clocks.sm",
        "clocks.mem",
        "power.draw",
        "utilization.gpu",
        "temperature.gpu",
    ]
    command = [
        "nvidia-smi",
        f"--query-gpu={','.join(fields)}",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(
            command,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False}

    rows = []
    for line in output.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != len(fields):
            continue
        rows.append(dict(zip(fields, values, strict=True)))
    return {"available": bool(rows), "gpus": rows}


def process_placement() -> dict[str, object]:
    """Return best-effort process affinity and current CPU placement."""

    placement: dict[str, object] = {
        "pid": os.getpid(),
        "processor_count": os.cpu_count(),
    }
    try:
        import psutil  # type: ignore[import-not-found]

        placement["cpu_affinity"] = psutil.Process().cpu_affinity()
    except Exception:
        placement["cpu_affinity"] = None

    if platform.system() == "Windows":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            placement["current_processor_number"] = int(
                kernel32.GetCurrentProcessorNumber()
            )
        except Exception:
            placement["current_processor_number"] = None
    return placement


def apply_cpu_affinity(pid: int, cpus: list[int]) -> dict[str, object]:
    """Best-effort child process affinity setter used by restart benchmarks."""

    if not cpus:
        return {"requested": [], "applied": None}
    try:
        import psutil  # type: ignore[import-not-found]

        process = psutil.Process(pid)
        process.cpu_affinity(cpus)
        return {"requested": cpus, "applied": process.cpu_affinity()}
    except Exception as exc:
        return {"requested": cpus, "applied": None, "error": str(exc)}


def _host_info() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def _python_info() -> dict[str, object]:
    return {
        "executable": sys.executable,
        "version": sys.version,
        "version_info": list(sys.version_info[:3]),
    }


def _package_versions(names: list[str]) -> dict[str, object]:
    versions: dict[str, object] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _import_provenance(names: list[str]) -> dict[str, object]:
    return {name: _module_provenance(name) for name in names}


def _module_provenance(name: str) -> dict[str, object]:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return {"available": False}

    origin = spec.origin
    locations = [
        str(location)
        for location in (spec.submodule_search_locations or [])
    ]
    path = _provenance_path(origin, locations)
    provenance: dict[str, object] = {
        "available": True,
        "origin": origin,
        "submodule_search_locations": locations,
    }
    distribution_name = _DISTRIBUTION_BY_MODULE.get(name)
    if distribution_name is not None:
        provenance["distribution"] = _distribution_provenance(distribution_name)
    if path is not None:
        source_git = _source_git_info(path)
        if source_git is not None:
            provenance["source_git"] = source_git
        elif _is_inside_virtual_environment(path):
            provenance["source_git"] = None
            provenance["source_git_note"] = (
                "suppressed for installed package inside venv"
            )
    return provenance


def _provenance_path(
    origin: str | None,
    locations: list[str],
) -> Path | None:
    if locations:
        return Path(locations[0])
    if origin is None:
        return None
    if origin in {"built-in", "frozen"}:
        return None
    return Path(origin)


def _torch_info() -> dict[str, object]:
    try:
        import torch  # type: ignore[import-not-found]

        return {
            "version": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _distribution_provenance(name: str) -> dict[str, object] | None:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None

    direct_url = None
    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct_url = {"raw": direct_url_text}
    try:
        package_name = distribution.metadata["Name"]
    except KeyError:
        package_name = name

    retained_wheels = _matching_retained_wheels(
        name,
        distribution.version,
    )
    installed_archive_sha256 = _direct_url_archive_sha256(direct_url)
    retained_wheel_sha256 = _single_retained_wheel_sha256(retained_wheels)
    match_verified, match_error = _verify_retained_wheel_match(
        package_name=name,
        installed_archive_sha256=installed_archive_sha256,
        retained_wheel_sha256=retained_wheel_sha256,
    )

    return {
        "name": package_name,
        "version": distribution.version,
        "location": str(distribution.locate_file("")),
        "installer": distribution.read_text("INSTALLER"),
        "direct_url": direct_url,
        "installed_archive_sha256": installed_archive_sha256,
        "retained_wheel_sha256": retained_wheel_sha256,
        "retained_wheel_match_verified": match_verified,
        "retained_wheel_match_error": match_error,
        "matching_retained_wheels": retained_wheels,
    }


def _direct_url_archive_sha256(direct_url: object) -> str | None:
    if not isinstance(direct_url, dict):
        return None
    archive_info = direct_url.get("archive_info")
    if not isinstance(archive_info, dict):
        return None
    hashes = archive_info.get("hashes")
    if isinstance(hashes, dict):
        sha256 = hashes.get("sha256")
        if isinstance(sha256, str) and sha256:
            return sha256
    archive_hash = archive_info.get("hash")
    if isinstance(archive_hash, str) and archive_hash.startswith("sha256="):
        return archive_hash.removeprefix("sha256=")
    return None


def _single_retained_wheel_sha256(wheels: list[dict[str, object]]) -> str | None:
    if len(wheels) != 1:
        return None
    sha256 = wheels[0].get("sha256")
    if isinstance(sha256, str) and sha256:
        return sha256
    return None


def _verify_retained_wheel_match(
    *,
    package_name: str,
    installed_archive_sha256: str | None,
    retained_wheel_sha256: str | None,
) -> tuple[bool | None, str | None]:
    if installed_archive_sha256 is None or retained_wheel_sha256 is None:
        return None, None
    if installed_archive_sha256 == retained_wheel_sha256:
        return True, None
    return (
        False,
        f"{package_name} installed archive sha256 does not match retained wheel: "
        f"{installed_archive_sha256} != {retained_wheel_sha256}",
    )


def _matching_retained_wheels(name: str, version: str) -> list[dict[str, object]]:
    wheels_dir = _REPO_ROOT / "dist" / "QwenTTSBridge" / "worker-python" / "wheels"
    if not wheels_dir.is_dir():
        return []

    normalized_prefix = f"{_wheel_normalize(name)}-{version}-"
    matches = []
    for wheel in sorted(wheels_dir.glob("*.whl")):
        if not wheel.name.lower().startswith(normalized_prefix):
            continue
        matches.append(
            {
                "file": str(wheel),
                "sha256": _sha256_file(wheel),
                "size_bytes": wheel.stat().st_size,
            }
        )
    return matches


def _wheel_normalize(name: str) -> str:
    return name.replace("-", "_").replace(".", "_").lower()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_git_info(path: Path) -> dict[str, object] | None:
    if _is_inside_virtual_environment(path):
        return None
    git_path = path if path.is_dir() else path.parent
    root = _git_output(git_path, "rev-parse", "--show-toplevel")
    if not root:
        return None
    info = _git_info(Path(root))
    info["root"] = root
    return info


def _is_inside_virtual_environment(path: Path) -> bool:
    current = path.resolve()
    if current.is_file():
        current = current.parent
    for parent in [current, *current.parents]:
        if (parent / "pyvenv.cfg").is_file():
            return True
    return False


def _git_info(path: Path) -> dict[str, object]:
    git_path = path if path.is_dir() else path.parent
    return {
        "commit": _git_output(git_path, "rev-parse", "HEAD"),
        "dirty": bool(_git_output(git_path, "status", "--porcelain")),
    }


def _git_output(path: Path, *args: str) -> str | None:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(path), *args],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return output.strip()


def _worker_info(
    worker_executable: Path,
    worker_prefix_args: list[str],
) -> dict[str, object]:
    manifest = _portable_manifest(worker_executable)
    return {
        "executable": str(worker_executable),
        "prefix_args": worker_prefix_args,
        "portable_manifest": manifest,
    }


def _portable_manifest(worker_executable: Path) -> dict[str, object] | None:
    worker_root = worker_executable.parent
    manifest_path = worker_root / "build-manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _qwen_config(args: Any) -> dict[str, object]:
    return {
        "engine": getattr(args, "engine", None),
        "model_path": getattr(args, "model_path", None),
        "runtime_backend": getattr(args, "runtime_backend", None),
        "device": getattr(args, "device", None),
        "dtype": getattr(args, "dtype", None),
        "attn_implementation": getattr(args, "attn_implementation", None),
        "emit_every_frames": getattr(args, "emit_every_frames", None),
        "decode_window_frames": getattr(args, "decode_window_frames", None),
        "overlap_samples": getattr(args, "overlap_samples", None),
        "max_seq_len": getattr(args, "max_seq_len", None),
        "seed": getattr(args, "seed", None),
        "seed_mode": getattr(args, "seed_mode", None),
        "warmup_seed": getattr(args, "warmup_seed", None),
        "profile_prefill": getattr(args, "profile_prefill", None),
        "profile_nvtx": getattr(args, "profile_nvtx", None),
        "do_sample": not bool(getattr(args, "no_sample", False)),
        "engine_startup_mode": getattr(args, "engine_startup_mode", None),
    }
