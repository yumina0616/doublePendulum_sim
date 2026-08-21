#!/usr/bin/env python3
"""Phase 6, step 1: failure store.

Scans every completed agentic task under tasks/<TASK-ID>/ for a failed
result (result.json's "passed" field is false), cross-references its
specification.yaml's allowed_changes to know which files the task touched,
and writes one structured record per failure to failure_store.jsonl.

This is read-only over tasks/ -- it never edits a task's own artifacts.
Re-run any time after new tasks complete; it always rewrites the whole
store from scratch (tasks/ is the source of truth, this is a derived index).

    python3 failure_store.py [--tasks-dir ../tasks] [--out failure_store.jsonl]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

def _load_yaml(path: Path):
    """These specification.yaml files are hand-written with prose
    descriptions inside list items (e.g. "file.py (reason: because X)"),
    which is not strict YAML -- a literal colon inside a plain scalar
    breaks real parsers. We only ever need the allowed_changes list here,
    so extract it by regex unconditionally instead of depending on every
    spec file being strictly parseable."""
    import re
    text = path.read_text()
    m = re.search(r"^allowed_changes:\n((?:  - .*\n(?:    .*\n)*)+)", text, re.MULTILINE)
    changes = []
    if m:
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                changes.append(stripped[2:])
    return {"allowed_changes": changes}


def scan(tasks_dir: Path) -> list[dict]:
    records = []
    for task_dir in sorted(tasks_dir.iterdir()):
        result_path = task_dir / "result.json"
        spec_path = task_dir / "specification.yaml"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text())
        if result.get("passed", True):
            continue  # only interested in failures

        allowed_changes = []
        if spec_path.exists():
            spec = _load_yaml(spec_path)
            allowed_changes = spec.get("allowed_changes", []) or []

        records.append({
            "task_id": result.get("task_id", task_dir.name),
            "task_dir": task_dir.name,
            "goal": result.get("goal", ""),
            "allowed_changes": allowed_changes,
            "notes": result.get("notes", ""),
            "verification_run": result.get("verification_run", {}),
        })
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", default=str(Path(__file__).resolve().parent.parent / "tasks"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "failure_store.jsonl"))
    args = ap.parse_args()

    records = scan(Path(args.tasks_dir))
    out_path = Path(args.out)
    with out_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"Scanned {args.tasks_dir}: {len(records)} failure record(s) written to {out_path}")
    for r in records:
        print(f"  - {r['task_id']}: allowed_changes={r['allowed_changes']}")


if __name__ == "__main__":
    main()
