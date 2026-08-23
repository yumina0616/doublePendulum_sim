"""Shared regex-based loader for the `allowed_changes:` / `forbidden_changes:`
list fields in a task's specification.yaml.

These files are hand-written with prose descriptions inside list items
(e.g. "file.py (reason: because X)"), which is not strict YAML -- a
literal colon inside a plain scalar breaks real parsers. Only the flat
list fields are ever needed by tooling, so extract them by regex
unconditionally instead of depending on every spec file being strictly
parseable (this is the same approach failure_store.py already used for
allowed_changes; generalized here so check_forbidden_changes.py can reuse
it for forbidden_changes too)."""
from __future__ import annotations

import re


def load_list_field(text: str, name: str) -> list[str]:
    m = re.search(rf"^{name}:\n((?:  - .*\n(?:    .*\n)*)+)", text, re.MULTILINE)
    items = []
    if m:
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:])
    return items
