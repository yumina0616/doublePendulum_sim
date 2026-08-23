#!/usr/bin/env python3
"""Phase 7: stale rule detection.

Scans skills/active/*.yaml and flags any skill where either:
  (a) negative_regression_count > 0 (the skill has already caused a
      measured regression since activation), or
  (b) a file matching the skill's own trigger.changed_files patterns was
      touched by a git commit AFTER the skill's last_verified_date -- i.e.
      the exact kind of change the skill's evidence was built on has
      happened again since, without the skill being re-verified against it.

Flagging only PROPOSES a status transition (active -> candidate_for_retirement).
It never retires anything by itself -- project_plan.md section 13's lifecycle
requires flagged skills to still pass through retirement_eval (see
retire_skill.py) before landing on retired/active.

    python3 stale_check.py [--active-dir skills/active]
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from skill_yaml import get_field, get_list_field


def _parse_skill(path: Path) -> dict:
    text = path.read_text()
    return {
        "path": path,
        "id": get_field(text, "id"),
        "status": get_field(text, "status"),
        "trigger_files": get_list_field(text, "changed_files"),
        "last_verified_date": get_field(text, "last_verified_date"),
        "negative_regression_count": int(get_field(text, "negative_regression_count") or 0),
    }


def _latest_commit_touching(repo_root: Path, pattern: str) -> str | None:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", pattern],
        cwd=repo_root, capture_output=True, text=True,
    )
    date = out.stdout.strip()
    return date or None


def check(active_dir: Path, repo_root: Path) -> list[dict]:
    flags = []
    for path in sorted(active_dir.glob("*.yaml")):
        skill = _parse_skill(path)
        reasons = []

        if skill["negative_regression_count"] > 0:
            reasons.append(
                f"negative_regression_count={skill['negative_regression_count']} > 0"
            )

        if skill["last_verified_date"] and skill["last_verified_date"] != "None":
            newest = None
            for pat in skill["trigger_files"]:
                d = _latest_commit_touching(repo_root, pat)
                if d and (newest is None or d > newest):
                    newest = d
            if newest and newest > skill["last_verified_date"]:
                reasons.append(
                    f"trigger-matched files changed on {newest[:10]}, after "
                    f"last_verified_date {skill['last_verified_date'][:10]}"
                )

        if reasons:
            flags.append({"id": skill["id"], "path": path, "reasons": reasons})

    return flags


def main():
    here = Path(__file__).resolve().parent
    repo_root = here.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--active-dir", default=str(here / "skills" / "active"))
    args = ap.parse_args()

    active_dir = Path(args.active_dir)
    flags = check(active_dir, repo_root)

    if not flags:
        print("no stale skills detected")
        return

    for f in flags:
        print(f"STALE CANDIDATE: {f['id']} ({f['path']})")
        for r in f["reasons"]:
            print(f"  - {r}")


if __name__ == "__main__":
    main()
