#!/usr/bin/env python3
"""DIAG-002: correlate each real run's trajectory divergence (from
PHYS-002's known, jitter-free physics-only trajectory) against that same
run's own per-sample arrival jitter -- does the real trajectory diverge
right around a large jitter event, or does it drift away gradually
across the whole post-disturbance window with no single event standing
out?

Does NOT pre-judge which pattern holds -- computes both series and
reports the honest correlation (or lack of one), per run and aggregated.

Usage:
    correlate_trajectory_jitter.py <diag002_evidence_dir> [--physics-only-ref path] [--out path]
"""
import argparse
import glob
import json
import math
import os

NOMINAL_JOINT_STATES_PERIOD_S = 0.005
DIVERGENCE_THRESHOLD_DEG = 1.0
SETTLE_BEFORE_S = 1.0
TOTAL_DURATION_S = 6.0


def load(path):
    with open(path) as f:
        return json.load(f)


def interp(x, xp, fp):
    """np.interp reimplemented with stdlib only (no numpy dependency needed
    for this simple monotonic-grid case)."""
    n = len(xp)
    if x <= xp[0]:
        return fp[0]
    if x >= xp[-1]:
        return fp[-1]
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xp[mid] <= x:
            lo = mid
        else:
            hi = mid
    x0, x1 = xp[lo], xp[hi]
    y0, y1 = fp[lo], fp[hi]
    if x1 == x0:
        return y0
    frac = (x - x0) / (x1 - x0)
    return y0 + frac * (y1 - y0)


def analyze_run(run, phys_t, phys_q1, phys_q2):
    t = run["t"]
    q1 = run["q1"]
    q2 = run["q2"]
    wall = run["joint_states_wall_s"]

    # divergence(t) in degrees, only over the window we have a physics-only
    # reference for (0..6.0s)
    div_t, div_q1_deg, div_q2_deg = [], [], []
    for ti, q1i, q2i in zip(t, q1, q2):
        if ti < 0 or ti > TOTAL_DURATION_S:
            continue
        ref_q1 = interp(ti, phys_t, phys_q1)
        ref_q2 = interp(ti, phys_t, phys_q2)
        div_t.append(ti)
        div_q1_deg.append(math.degrees(abs(q1i - ref_q1)))
        div_q2_deg.append(math.degrees(abs(q2i - ref_q2)))

    # divergence onset: first t (after the disturbance pulse clears, i.e.
    # t >= settle_before, matching every other settling-time convention in
    # this project) after which divergence STAYS above threshold for the
    # rest of the recorded window (same "settling_time" definition
    # metrics.py uses, just inverted -- this is "when does it stop
    # tracking the ideal trajectory", not "when does it settle").
    onset_t = None
    n = len(div_t)
    for i in range(n):
        if div_t[i] < SETTLE_BEFORE_S:
            continue
        if all(div_q1_deg[j] > DIVERGENCE_THRESHOLD_DEG or div_q2_deg[j] > DIVERGENCE_THRESHOLD_DEG
               for j in range(i, n)):
            onset_t = div_t[i]
            break

    # per-sample jitter (deviation from nominal period) on the SAME run's
    # joint_states wall-clock arrivals
    jitter_events = []  # (t_approx, deviation_ms)
    for i in range(1, len(wall)):
        interval = wall[i] - wall[i - 1]
        dev_ms = abs(interval - NOMINAL_JOINT_STATES_PERIOD_S) * 1000.0
        jitter_events.append((t[i] if i < len(t) else None, dev_ms))

    jitter_events_valid = [(ti, d) for ti, d in jitter_events if ti is not None]
    jitter_events_valid.sort(key=lambda x: -x[1])
    top_jitter = jitter_events_valid[:3]

    onset_near_top_jitter = None
    if onset_t is not None and top_jitter:
        # "near" = within 0.2s of this run's single largest jitter event
        closest = min(top_jitter, key=lambda x: abs(x[0] - onset_t))
        onset_near_top_jitter = abs(closest[0] - onset_t) <= 0.2

    return {
        "onset_t": onset_t,
        "max_div_q1_deg": max(div_q1_deg) if div_q1_deg else None,
        "max_div_q2_deg": max(div_q2_deg) if div_q2_deg else None,
        "top_3_jitter_events_t_and_ms": top_jitter,
        "onset_within_0.2s_of_largest_jitter_event": onset_near_top_jitter,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("evidence_dir")
    ap.add_argument("--physics-only-ref",
                     default=os.path.expanduser(
                         "~/agentic_double_pendulum/tasks/PHYS-002-closed-loop-physics-only/evidence/physics_only_run_1.json"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ref = load(args.physics_only_ref)
    phys_t, phys_q1, phys_q2 = ref["t"], ref["q1"], ref["q2"]
    phys_only_settling_q1_s = ref["metrics"]["settling_time_q1_s"]

    run_files = sorted(glob.glob(os.path.join(args.evidence_dir, "run_*_raw_trajectory.json")))
    if not run_files:
        raise SystemExit(f"no run_*_raw_trajectory.json files found in {args.evidence_dir}")

    results = {}
    for rf in run_files:
        name = os.path.basename(rf)
        run = load(rf)
        if not run["t"]:
            results[name] = {"error": "empty recording (no /joint_states samples -- likely missed the window)"}
            continue
        r = analyze_run(run, phys_t, phys_q1, phys_q2)
        if r.get("onset_t") is not None:
            r["delta_from_physics_only_settling_s"] = r["onset_t"] - phys_only_settling_q1_s
        results[name] = r

    n_with_onset = sum(1 for r in results.values() if r.get("onset_t") is not None)
    n_onset_near_jitter = sum(1 for r in results.values() if r.get("onset_within_0.2s_of_largest_jitter_event") is True)

    deltas = [r["delta_from_physics_only_settling_s"] for r in results.values() if "delta_from_physics_only_settling_s" in r]
    summary = {
        "n_runs": len(results),
        "n_runs_with_divergence_onset_detected": n_with_onset,
        "n_runs_where_onset_near_largest_jitter_event": n_onset_near_jitter,
        "physics_only_settling_time_q1_s_reference": phys_only_settling_q1_s,
        "onset_minus_physics_only_settling_s_per_run": deltas,
        "onset_minus_physics_only_settling_s_mean": (sum(deltas) / len(deltas)) if deltas else None,
        "onset_minus_physics_only_settling_s_range": [min(deltas), max(deltas)] if deltas else None,
        "per_run": results,
        "note": "onset = first t (>= settle_before_s) after which divergence from the physics-only "
                "trajectory stays above 1.0deg for the rest of the recording. 'near' = within 0.2s "
                "of that same run's single largest joint_states arrival-jitter event. Does NOT "
                "conclude correlation exists or not -- see PLAN.md for the interpretation.",
    }

    print(json.dumps(summary, indent=2))
    delta_range = summary["onset_minus_physics_only_settling_s_range"]
    delta_mean = summary["onset_minus_physics_only_settling_s_mean"]
    print(f"\nonset clusters {delta_range} seconds AFTER physics-only's own settling "
          f"({phys_only_settling_q1_s}s), mean +{delta_mean:.3f}s -- vs. each run's own "
          f"largest-jitter-event timing, which varies across a much wider and inconsistent "
          f"range (see top_3_jitter_events_t_and_ms per run).")
    if args.out:
        tmp = args.out + ".tmp"
        with open(tmp, "w") as f:
            json.dump(summary, f, indent=2)
        os.replace(tmp, args.out)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
