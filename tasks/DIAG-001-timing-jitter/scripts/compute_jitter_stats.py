#!/usr/bin/env python3
"""DIAG-001: aggregates the N raw per-run timestamp files
(run_<i>_raw_timestamps.json, written by measure_jitter.py) into
per-topic jitter statistics.

For each topic (joint_states wall-clock arrival, commands wall-clock
arrival), computes the inter-arrival interval sequence, then reports:
  - n_intervals, mean_interval_ms, std_interval_ms
  - nominal_period_ms (5ms for joint_states -- controller_manager's
    200Hz update_rate; 10ms for commands -- lqr_node.py's own 100Hz
    control timer)
  - mean/std/p95/p99/max of |interval - nominal_period| (deviation)

Also reports, for joint_states only, the sim-time vs wall-clock spacing
comparison: the ratio of wall-clock mean interval to sim-time mean
interval spacing -- if ROS2/DDS added no jitter and use_sim_time were
perfectly in lockstep with wall time, these would match closely.

Deliberately does NOT decide "jitter is significant" or "jitter is
negligible" -- per LQI_ROOT_CAUSE_PLAN.md, that judgment is deferred to
PHYS-002 (closed-loop physics-only comparison). This script only reports
the numbers.

Usage:
    compute_jitter_stats.py <evidence_dir> [--out jitter_stats.json]
"""
import argparse
import glob
import json
import os

import numpy as np

NOMINAL_PERIOD_S = {
    "joint_states": 0.005,   # controller_manager update_rate: 200 Hz
    "commands": 0.010,       # lqr_node.py's own control timer: 100 Hz
}


def interval_stats(timestamps, nominal_period_s):
    ts = np.asarray(timestamps, dtype=float)
    if len(ts) < 2:
        return None
    intervals = np.diff(ts)
    deviation = np.abs(intervals - nominal_period_s)
    return {
        "n_samples": int(len(ts)),
        "n_intervals": int(len(intervals)),
        "nominal_period_ms": nominal_period_s * 1000.0,
        "mean_interval_ms": float(np.mean(intervals) * 1000.0),
        "std_interval_ms": float(np.std(intervals) * 1000.0),
        "min_interval_ms": float(np.min(intervals) * 1000.0),
        "max_interval_ms": float(np.max(intervals) * 1000.0),
        "mean_abs_deviation_ms": float(np.mean(deviation) * 1000.0),
        "std_abs_deviation_ms": float(np.std(deviation) * 1000.0),
        "p95_abs_deviation_ms": float(np.percentile(deviation, 95) * 1000.0),
        "p99_abs_deviation_ms": float(np.percentile(deviation, 99) * 1000.0),
        "max_abs_deviation_ms": float(np.max(deviation) * 1000.0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("evidence_dir")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.evidence_dir, "run_*_raw_timestamps.json")))
    if not files:
        raise SystemExit(f"no run_*_raw_timestamps.json files found in {args.evidence_dir}")

    per_run = []
    all_joint_states_intervals_ms = []
    all_commands_intervals_ms = []

    for f in files:
        with open(f) as fh:
            raw = json.load(fh)
        js_wall = raw["joint_states_wall_s"]
        js_sim = raw["joint_states_sim_stamp_s"]
        cmd_wall = raw["commands_wall_s"]

        js_stats = interval_stats(js_wall, NOMINAL_PERIOD_S["joint_states"])
        cmd_stats = interval_stats(cmd_wall, NOMINAL_PERIOD_S["commands"])

        sim_vs_wall = None
        if len(js_sim) >= 2 and len(js_wall) >= 2:
            sim_intervals = np.diff(np.asarray(js_sim, dtype=float))
            wall_intervals = np.diff(np.asarray(js_wall, dtype=float))
            n = min(len(sim_intervals), len(wall_intervals))
            if n > 0:
                sim_vs_wall = {
                    "mean_sim_interval_ms": float(np.mean(sim_intervals[:n]) * 1000.0),
                    "mean_wall_interval_ms": float(np.mean(wall_intervals[:n]) * 1000.0),
                }

        per_run.append({
            "file": os.path.basename(f),
            "joint_states": js_stats,
            "commands": cmd_stats,
            "joint_states_sim_vs_wall": sim_vs_wall,
        })

        if js_stats:
            all_joint_states_intervals_ms.append(js_stats["std_interval_ms"])
        if cmd_stats:
            all_commands_intervals_ms.append(cmd_stats["std_interval_ms"])

    result = {
        "n_runs": len(files),
        "per_run": per_run,
        "aggregate": {
            "joint_states_std_interval_ms_across_runs": all_joint_states_intervals_ms,
            "commands_std_interval_ms_across_runs": all_commands_intervals_ms,
            "joint_states_mean_of_std_ms": float(np.mean(all_joint_states_intervals_ms)) if all_joint_states_intervals_ms else None,
            "commands_mean_of_std_ms": float(np.mean(all_commands_intervals_ms)) if all_commands_intervals_ms else None,
        },
        "note": "jitter significance is NOT judged here -- see PLAN.md / private/LQI_ROOT_CAUSE_PLAN.md Task B (PHYS-002) for interpretation.",
    }

    out_path = args.out or os.path.join(args.evidence_dir, "jitter_stats.json")
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=2)
    os.replace(tmp, out_path)
    print(f"wrote {out_path}")
    print(json.dumps(result["aggregate"], indent=2))


if __name__ == "__main__":
    main()
