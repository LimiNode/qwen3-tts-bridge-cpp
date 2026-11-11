"""Shared Qwen adapter failures, independent of engine orchestration."""

class QwenEngineError(RuntimeError):
    """Raised when the Qwen adapter cannot load or run the model."""
