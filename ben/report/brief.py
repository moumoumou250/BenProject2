"""Slim surface for hooks: status + history without importing the full package."""
from __future__ import annotations

from ben.report.history import render_history_block
from ben.report.status import render_status

__all__ = ["render_status", "render_history_block"]
