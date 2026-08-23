#!/usr/bin/env python3
"""Phase 7: skill retirement lifecycle.

Implements the rest of project_plan.md section 13's state machine (the
candidate -> active half is promote_skill.py from Phase 6):

    active -> candidate_for_retirement -> retirement_eval -> retired | active

Two subcommands:

  flag   active -> candidate_for_retirement. A proposal only (mirrors
         propose_skill.py: evidence-gathering doesn't need approval).
         Reason usually comes from stale_check.py's output but can be
         given directly.

  eval   candidate_for_retirement -> retirement_eval -> final decision.
         Re-runs the SAME differential comparison promote_skill.py uses
         (does the skill-applied condition still beat the skill-disabled
         condition?) against fresh baseline/candidate summaries. If the
         skill still wins, it returns to active with an updated
         last_verified_date (re-verified, not retired). If it no longer
         wins, it is retired: moved to skills/retired/, status set to
         retired.

         The final decision (the only step that actually removes a skill
         from active/) requires --approved-by, per project_plan.md section
         16's "approval gate" principle -- this script refuses to write a
         retired/active decision without a named human approver.

    python3 retire_skill.py flag --skill SKILL-X --reason "..."
    python3 retire_skill.py eval --skill SKILL-X \\
        --baseline-summary /tmp/x_baseline.json \\
        --candidate-summary /tmp/x_candidate.json \\
        --verified-by TASK-123 --approved-by "your name"
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from skill_yaml import get_field, set_field


def decide_reverify(baseline: dict, candidate: dict) -> tuple[bool, str]:
    """Same rule as promote_skill.py's decide(): candidate must strictly
    beat baseline. Ties or worse => retire, not a coin flip toward keeping
    an active skill alive."""
    b_rate, c_rate = baseline["pass_rate"], candidate["pass_rate"]
    if c_rate > b_rate:
        return True, f"candidate pass_rate {c_rate} still > baseline pass_rate {b_rate} -- re-verified"
    return False, f"candidate pass_rate {c_rate} no longer beats baseline pass_rate {b_rate} -- retiring"


def cmd_flag(args):
    here = Path(__file__).resolve().parent
    active_dir = Path(args.active_dir or here / "skills" / "active")
    skill_path = active_dir / f"{args.skill}.yaml"
    if not skill_path.exists():
        raise SystemExit(f"no active skill at {skill_path}")

    text = skill_path.read_text()
    if get_field(text, "status") != "active":
        raise SystemExit(f"{skill_path} is not status: active (can only flag active skills)")

    today = datetime.date.today().isoformat()
    text = set_field(text, "status", "candidate_for_retirement")
    text = set_field(text, "retirement_flagged_reason", f'"{args.reason}"')
    text = set_field(text, "retirement_flagged_at", today)
    skill_path.write_text(text)
    print(f"{args.skill}: active -> candidate_for_retirement")
    print(f"  reason: {args.reason}")


def cmd_eval(args):
    here = Path(__file__).resolve().parent
    active_dir = Path(args.active_dir or here / "skills" / "active")
    retired_dir = Path(args.retired_dir or here / "skills" / "retired")
    skill_path = active_dir / f"{args.skill}.yaml"
    if not skill_path.exists():
        raise SystemExit(f"no skill at {skill_path}")

    text = skill_path.read_text()
    if get_field(text, "status") != "candidate_for_retirement":
        raise SystemExit(
            f"{skill_path} is not status: candidate_for_retirement (run 'flag' first)"
        )

    if not args.approved_by:
        raise SystemExit(
            "refusing to finalize a retirement decision without --approved-by "
            "(project_plan.md section 16 approval gate)"
        )

    baseline = json.loads(Path(args.baseline_summary).read_text())
    candidate = json.loads(Path(args.candidate_summary).read_text())
    keep_active, reason = decide_reverify(baseline, candidate)
    today = datetime.date.today().isoformat()

    print("=" * 70)
    print(f"Skill: {args.skill}")
    print(f"Baseline (no skill):    n={baseline['n_runs']} pass_rate={baseline['pass_rate']}")
    print(f"Candidate (skill applied): n={candidate['n_runs']} pass_rate={candidate['pass_rate']}")
    print(f"Retirement eval decision: {'STAY ACTIVE (re-verified)' if keep_active else 'RETIRE'} -- {reason}")
    print(f"Approved by: {args.approved_by}")
    print("=" * 70)

    text = set_field(text, "status", "retirement_eval")
    text = set_field(text, "retirement_eval_decision", "STAY_ACTIVE" if keep_active else "RETIRE")
    text = set_field(text, "retirement_eval_reason", f'"{reason}"')
    text = set_field(text, "retirement_eval_verified_by", args.verified_by)
    text = set_field(text, "retirement_eval_approved_by", f'"{args.approved_by}"')
    text = set_field(text, "retirement_eval_at", today)

    if keep_active:
        text = set_field(text, "status", "active")
        text = set_field(text, "last_verified", args.verified_by)
        text = set_field(text, "last_verified_date", today)
        skill_path.write_text(text)
        print(f"Kept active (re-verified): {skill_path}")
    else:
        text = set_field(text, "status", "retired")
        text = set_field(text, "retired_at", today)
        retired_dir.mkdir(parents=True, exist_ok=True)
        dest = retired_dir / skill_path.name
        dest.write_text(text)
        skill_path.unlink()
        print(f"Retired: {dest}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_flag = sub.add_parser("flag", help="active -> candidate_for_retirement")
    p_flag.add_argument("--skill", required=True)
    p_flag.add_argument("--reason", required=True)
    p_flag.add_argument("--active-dir", default=None)
    p_flag.set_defaults(func=cmd_flag)

    p_eval = sub.add_parser("eval", help="candidate_for_retirement -> retired | active")
    p_eval.add_argument("--skill", required=True)
    p_eval.add_argument("--baseline-summary", required=True)
    p_eval.add_argument("--candidate-summary", required=True)
    p_eval.add_argument("--verified-by", required=True)
    p_eval.add_argument("--approved-by", required=True)
    p_eval.add_argument("--active-dir", default=None)
    p_eval.add_argument("--retired-dir", default=None)
    p_eval.set_defaults(func=cmd_eval)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
