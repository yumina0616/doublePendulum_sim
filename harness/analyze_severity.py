#!/usr/bin/env python3
"""HARNESS-001 follow-up: compare failure SEVERITY (not just pass/fail
threshold) between two conditions, using the per-run result.json snapshots
run_repeated_experiment.sh now saves to /tmp/repeated_<scenario>_run<i>_result.json.

Motivation: nominal_balance's settling_time_q1 criterion already fails
almost universally in this environment (see CTRL-003/004), even with a
correctly-matched plant -- so raw pass_rate can't separate "the plant/model
mismatch made things worse" from "this scenario just always narrowly
fails". A run is instead called "catastrophic" if it shows real
instability (stable=false) or a large overshoot (>100 deg on either
joint) -- a threshold well above the ~16-18 deg seen in every matched-plant
run so far, and well below the 200+ deg seen in every mismatched
catastrophic run so far.

    python3 analyze_severity.py --glob "/tmp/repeated_nominal_balance_run*_result.json" --label baseline
"""
from __future__ import annotations

import argparse
import glob
import json

CATASTROPHIC_OVERSHOOT_DEG = 100.0


def is_catastrophic(result: dict) -> bool:
    m = result.get("metrics", result)  # real result.json nests under "metrics"; tolerate flat too
    if m.get("stable") is False:
        return True
    if m.get("overshoot_q1_deg", 0) > CATASTROPHIC_OVERSHOOT_DEG:
        return True
    if m.get("overshoot_q2_deg", 0) > CATASTROPHIC_OVERSHOOT_DEG:
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", required=True)
    ap.add_argument("--label", default="condition")
    args = ap.parse_args()

    paths = sorted(glob.glob(args.glob))
    if not paths:
        print(f"no files matched {args.glob}")
        return

    n = len(paths)
    n_catastrophic = 0
    for p in paths:
        r = json.loads(open(p).read())
        m = r.get("metrics", r)
        cat = is_catastrophic(r)
        n_catastrophic += cat
        print(f"  {p}: stable={m.get('stable')} overshoot_q1={m.get('overshoot_q1_deg'):.1f} "
              f"overshoot_q2={m.get('overshoot_q2_deg'):.1f} max_tau1={m.get('max_abs_tau1_nm'):.1f} "
              f"{'*** CATASTROPHIC ***' if cat else ''}")

    rate = n_catastrophic / n
    print(f"\n[{args.label}] catastrophic_rate = {n_catastrophic}/{n} = {rate:.2f}")


if __name__ == "__main__":
    main()
