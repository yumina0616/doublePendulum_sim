#!/usr/bin/env python3
"""Phase 6, steps 5-7: regression-gated skill promotion.

Compares a baseline run (skill's procedure NOT applied) against a candidate
run (skill's procedure applied) using their run_repeated_experiment.sh
summary JSONs, and decides PROMOTE or REJECT.

Simplified promotion gate vs project_plan.md section 12's full version (no
large benchmark suite yet to measure token_cost/tool_calls deltas across
many tasks) -- for this MVP: PROMOTE iff candidate.pass_rate is strictly
better than baseline.pass_rate. This is intentionally conservative: a tie
or a worse candidate is REJECT, not a coin flip toward promotion.

Promotion (unlike proposal) mutates the trusted skills/active/ store, so
per project_plan.md section 16's approval gate principle this script
refuses to PROMOTE without --approved-by naming a human approver (REJECT
needs no approval -- rejecting doesn't grant a skill any new trust).

On PROMOTE: moves the skill YAML from skills/candidates/ to
skills/active/, sets status: active, last_verified/last_verified_date,
activation_count += 1, success_after_activation += 1 if the candidate run
itself passed its own threshold.
On REJECT: skill stays in candidates/, a rejection note (with the numbers)
is appended so the decision is auditable later, not silently dropped.

    python3 promote_skill.py --skill SKILL-CONTROL-MODEL-CONSISTENCY \\
        --baseline-summary /tmp/repeated_nominal_balance_summary_baseline.json \\
        --candidate-summary /tmp/repeated_nominal_balance_summary_candidate.json \\
        --verified-by BENCH-002 --approved-by "your name"
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from skill_yaml import get_field, set_field


def decide(baseline: dict, candidate: dict) -> tuple[bool, str]:
    b_rate, c_rate = baseline["pass_rate"], candidate["pass_rate"]
    if c_rate > b_rate:
        return True, f"candidate pass_rate {c_rate} > baseline pass_rate {b_rate}"
    return False, f"candidate pass_rate {c_rate} did not beat baseline pass_rate {b_rate}"


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True, help="skill id, e.g. SKILL-CONTROL-MODEL-CONSISTENCY")
    ap.add_argument("--baseline-summary", required=True)
    ap.add_argument("--candidate-summary", required=True)
    ap.add_argument("--verified-by", required=True, help="task id of the candidate-eval benchmark task")
    ap.add_argument("--approved-by", default=None, help="required to actually PROMOTE (approval gate)")
    ap.add_argument("--candidates-dir", default=str(here / "skills" / "candidates"))
    ap.add_argument("--active-dir", default=str(here / "skills" / "active"))
    args = ap.parse_args()

    baseline = json.loads(Path(args.baseline_summary).read_text())
    candidate = json.loads(Path(args.candidate_summary).read_text())
    promote, reason = decide(baseline, candidate)

    skill_path = Path(args.candidates_dir) / f"{args.skill}.yaml"
    text = skill_path.read_text()

    today = datetime.date.today().isoformat()
    print("=" * 70)
    print(f"Skill: {args.skill}")
    print(f"Baseline (no skill):    n={baseline['n_runs']} pass_rate={baseline['pass_rate']} verdict={baseline['verdict']}")
    print(f"Candidate (skill applied): n={candidate['n_runs']} pass_rate={candidate['pass_rate']} verdict={candidate['verdict']}")
    print(f"Decision: {'PROMOTE' if promote else 'REJECT'} -- {reason}")
    print("=" * 70)

    if promote and not args.approved_by:
        raise SystemExit(
            "PROMOTE decision reached, but refusing to write it without --approved-by "
            "(project_plan.md section 16 approval gate). Re-run with --approved-by "
            "once a human has reviewed the numbers above."
        )

    if promote:
        text = set_field(text, "status", "active")
        text = set_field(text, "last_verified", args.verified_by)
        text = set_field(text, "last_verified_date", today)
        text = set_field(text, "activation_count", str(int(get_field(text, "activation_count") or 0) + 1))
        success_delta = 1 if candidate["verdict"] == "PASS" else 0
        text = set_field(text, "success_after_activation", str(success_delta))
        text = set_field(text, "promotion_decision", "PROMOTE")
        text = set_field(text, "promotion_reason", f'"{reason}"')
        text = set_field(text, "promoted_at", today)
        text = set_field(text, "promotion_approved_by", f'"{args.approved_by}"')
        active_dir = Path(args.active_dir)
        active_dir.mkdir(parents=True, exist_ok=True)
        dest = active_dir / skill_path.name
        dest.write_text(text)
        skill_path.unlink()
        print(f"Moved to {dest}")
    else:
        text = set_field(text, "last_evaluation_decision", "REJECT")
        text = set_field(text, "last_evaluation_reason", f'"{reason}"')
        text = set_field(text, "last_evaluated_at", today)
        skill_path.write_text(text)
        print(f"Kept in candidates/ with rejection note appended: {skill_path}")


if __name__ == "__main__":
    main()
