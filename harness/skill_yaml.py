"""Tiny shared helpers for reading/mutating the hand-rolled skill YAML files
emitted by propose_skill.py. Not a real YAML parser -- the schema is a flat
set of top-level `key: value` lines plus a couple of known list blocks, and
these helpers are only used by the scripts that manage skill lifecycle
state (promote_skill.py, retire_skill.py, stale_check.py)."""
from __future__ import annotations

import re


def get_field(text: str, name: str) -> str | None:
    m = re.search(rf"^{name}: (.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def set_field(text: str, name: str, value: str) -> str:
    """Replace an existing top-level `name: ...` line if present, else
    append a new one at the end. Always leaves exactly one such line, so
    later reads (get_field, or a fresh regex scan) can't pick up a stale
    duplicate."""
    pattern = re.compile(rf"^{name}: .*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(f"{name}: {value}", text, count=1)
    return text.rstrip("\n") + f"\n{name}: {value}\n"


def get_list_field(text: str, name: str) -> list[str]:
    """Finds a `name:` block (at any indentation) followed by `- item`
    lines (at any deeper indentation) and returns the unquoted items."""
    m = re.search(rf"^[ \t]*{re.escape(name)}:\n((?:[ \t]+- .*\n)+)", text, re.MULTILINE)
    if not m:
        return []
    items = []
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip('"'))
    return items
