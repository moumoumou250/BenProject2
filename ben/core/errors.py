"""Package error type."""
from __future__ import annotations


class FGError(Exception):
    """User-facing error; message is printed, exit code 1."""
