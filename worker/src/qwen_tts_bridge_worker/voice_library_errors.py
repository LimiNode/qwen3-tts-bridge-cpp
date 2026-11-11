"""Errors shared by managed voice storage and native preparation."""


class VoiceLibraryError(ValueError):
    """Raised for invalid, conflicting, or unverifiable voice-library state."""
