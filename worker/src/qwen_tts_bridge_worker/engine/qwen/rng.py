"""Seed application and scoped preservation of model warmup RNG state."""

from __future__ import annotations

import hashlib
import importlib
import random
from collections.abc import Iterator
from contextlib import contextmanager

from qwen_tts_bridge_worker.engine.qwen.errors import QwenEngineError
from qwen_tts_bridge_worker.engine.types import EngineRequestValidationError


def _seed_runtime(
    seed: int | None,
    *,
    strict: bool = False,
    require_cuda: bool = False,
) -> None:
    if seed is None:
        return
    failures: list[str] = []
    try:
        random.seed(seed)
    except Exception as exc:
        failures.append(f"Python RNG: {exc}")
    try:
        numpy = importlib.import_module("numpy")
        numpy.random.seed(seed % (2**32))
    except Exception as exc:
        failures.append(f"NumPy RNG: {exc}")
    try:
        torch = importlib.import_module("torch")
        torch.manual_seed(seed)
        cuda = getattr(torch, "cuda", None)
        manual_seed_all = getattr(cuda, "manual_seed_all", None)
        if require_cuda and not callable(manual_seed_all):
            raise RuntimeError("torch.cuda.manual_seed_all is unavailable")
        if require_cuda:
            assert callable(manual_seed_all)
            manual_seed_all(seed)
    except Exception as exc:
        failures.append(f"Torch RNG: {exc}")

    if strict and failures:
        raise EngineRequestValidationError(
            "seed_application_failed",
            "could not apply explicit seed to all required RNGs: "
            + "; ".join(failures),
        )


def _rng_state_fingerprint(*, require_cuda: bool = True) -> dict[str, str]:
    """Return stable hashes for every RNG state guarded by warmup passes."""

    try:
        numpy = importlib.import_module("numpy")
        torch = importlib.import_module("torch")
        cuda_available = bool(torch.cuda.is_available())
        if require_cuda and not cuda_available:
            raise QwenEngineError("strict generation prime requires CUDA RNG state")
        numpy_state = numpy.random.get_state()
        torch_cpu_state = torch.get_rng_state().cpu().numpy().tobytes()
        cuda_states = torch.cuda.get_rng_state_all() if cuda_available else ()
    except QwenEngineError:
        raise
    except Exception as exc:
        raise QwenEngineError(
            "failed to fingerprint generation-prime RNG state"
        ) from exc

    def digest(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    numpy_bytes = b"".join(
        (
            str(numpy_state[0]).encode("ascii"),
            numpy_state[1].tobytes(),
            str(numpy_state[2:]).encode("ascii"),
        )
    )
    return {
        "python_sha256": digest(repr(random.getstate()).encode("utf-8")),
        "numpy_sha256": digest(numpy_bytes),
        "torch_cpu_sha256": digest(torch_cpu_state),
        "torch_cuda_sha256": digest(
            b"".join(state.cpu().numpy().tobytes() for state in cuda_states)
        ),
    }


@contextmanager
def _preserved_rng_state(*, require_cuda: bool = True) -> Iterator[None]:
    python_state = random.getstate()
    try:
        numpy = importlib.import_module("numpy")
        numpy_state = numpy.random.get_state()
    except Exception as exc:
        raise QwenEngineError("failed to capture NumPy RNG state") from exc
    try:
        torch = importlib.import_module("torch")
        torch_cpu_state = torch.get_rng_state()
        cuda_available = bool(torch.cuda.is_available())
        if require_cuda and not cuda_available:
            raise QwenEngineError("strict first-chunk warmup requires CUDA RNG state")
        torch_cuda_states = torch.cuda.get_rng_state_all() if cuda_available else None
    except QwenEngineError:
        raise
    except Exception as exc:
        raise QwenEngineError("failed to capture torch RNG state") from exc
    try:
        yield
    finally:
        try:
            random.setstate(python_state)
            numpy.random.set_state(numpy_state)
            torch.set_rng_state(torch_cpu_state)
            if torch_cuda_states is not None:
                torch.cuda.set_rng_state_all(torch_cuda_states)
        except Exception as exc:
            raise QwenEngineError("failed to restore strict warmup RNG state") from exc
