"""Shared constants."""
from __future__ import annotations

import re

__version__ = "1.0.0"


GOAL_ID = "goal"


DEFAULT_STORE = ".ben"


LOCK_NAME = ".lock"


PEERS_FILE = "ai-peers.json"


AI_CHANNEL_NAME = "ai-channel.txt"


PEER_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


_UNSET = object()


FACT_KINDS = ("host", "service", "cred", "vuln", "loot", "flag", "note")


DATA_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_VALID_NODE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,16}$")
