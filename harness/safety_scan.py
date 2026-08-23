"""Phase 7 follow-up (SEC-002): denylist scan over a skill's procedure text.

promote_skill.py / retire_skill.py's --approved-by is a PROCEDURAL gate
(someone must type a name) but not a SUBSTANTIVE one -- nothing confirms
the approver actually read the procedure (see
tasks/SEC-002-poisoned-skill/FINDINGS.md, which demonstrated a real
promote_skill.py run promoting an actuator-limit-bypassing skill on
fabricated numbers alone). This scans a skill's `procedure` list for
keywords associated with known-unsafe shortcuts and, if any match,
requires an extra explicit acknowledgement flag before a trust-granting
decision (PROMOTE, or retirement-eval's STAY_ACTIVE) can be finalized.

A keyword match is not proof of an unsafe skill -- a legitimate skill
could mention "torque limit" while describing a proper fix -- so this is
a forcing function, not a hard block: always overridable with
--acknowledge-safety-warning, never silently skipped.
"""
from __future__ import annotations

from skill_yaml import get_list_field

SAFETY_DENYLIST_KEYWORDS = [
    "tau1_max", "tau2_max", "tau_max", "torque limit", "actuator limit",
    "effort limit", "disable", "skip regression", "bypass",
    "remove saturation", "ignore acceptance",
]


def scan_procedure(skill_text: str) -> list[str]:
    procedure = get_list_field(skill_text, "procedure")
    combined = " ".join(procedure).lower()
    return [kw for kw in SAFETY_DENYLIST_KEYWORDS if kw in combined]


def print_warning(matched: list[str]) -> None:
    print("!" * 70)
    print(f"SAFETY WARNING: procedure text matches denylist keyword(s): {matched}")
    print("Review the procedure above BEFORE approving. A match is not proof")
    print("of an unsafe skill, but requires --acknowledge-safety-warning to")
    print("proceed -- typing --approved-by alone is not enough here.")
    print("!" * 70)
