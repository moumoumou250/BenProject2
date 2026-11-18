"""trange — start a vulnerable-lab range and prove the link.

Scope is deliberately narrow: this package does exactly two things.

  * **start** — bring the range up (existing container, plain image, or compose
    scenario) and move it to a free port when the declared one is taken.
  * **self-check** — prove that something on this host can talk to it right now,
    and write ``connect.env`` so the caller does not have to re-derive the URL.

Everything that happens after "it is connected" (exploitation, evidence,
scoring) belongs to the operator's main flow, not here.

A new range needs one profile file and zero lines of code. Standard library
only, matching the BenProject kernel rule (see docs/ARCH.md).
"""

from .profiles import Profile, ProfileError, discover_profiles, load_profile
from .runner import RangeRun, run_range
from . import connect, dockerops, ports

__all__ = [
    "Profile",
    "ProfileError",
    "load_profile",
    "discover_profiles",
    "RangeRun",
    "run_range",
    "connect",
    "dockerops",
    "ports",
]
