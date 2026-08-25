#!/usr/bin/env python3
"""REFACTOR-001: precompute and cache LQR gains, keyed by the current
plant_params.yaml's hash plus the requested Q/R weights.

lqr_node.py loads this cache instead of recomputing the gain (a ~1
minute CARE solve) inline on every single startup, AND refuses to start
if the cache's plant_hash/q_diag/r_diag don't match what's requested at
run time -- turning "someone edited plant_params.yaml (or asked for
different Q/R weights) and forgot to redesign the gain" into a loud,
immediate failure instead of a silently-wrong controller running against
stale numbers. This is what SKILL-CONTROL-MODEL-CONSISTENCY (see
harness/skills/retired/) used to rely on a human/agent remembering to do
by hand.

Usage:
    design_lqr_gains.py
    design_lqr_gains.py --q1 100 --q2 100 --q1d 10 --q2d 10 --qi1 10 --qi2 10 --r1 0.05 --r2 0.05
"""
import argparse
import json
import os
import time

from lqr_controller import design_lqr
from plant_params import load_plant_params, plant_hash

CACHE_FILENAME = "lqr_gain_cache.json"


def cache_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CACHE_FILENAME)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--q1", type=float, default=50.0)
    parser.add_argument("--q2", type=float, default=50.0)
    parser.add_argument("--q1d", type=float, default=5.0)
    parser.add_argument("--q2d", type=float, default=5.0)
    parser.add_argument("--qi1", type=float, default=10.0)
    parser.add_argument("--qi2", type=float, default=10.0)
    parser.add_argument("--r1", type=float, default=0.05)
    parser.add_argument("--r2", type=float, default=0.05)
    args = parser.parse_args()

    q_diag = (args.q1, args.q2, args.q1d, args.q2d, args.qi1, args.qi2)
    r_diag = (args.r1, args.r2)

    plant = load_plant_params()
    h = plant_hash(plant)

    print(f"plant_hash={h}")
    print("designing LQR gain (linearizing + solving CARE, ~1 min)...")
    start = time.time()
    gains = design_lqr(q_diag=q_diag, r_diag=r_diag)
    elapsed = time.time() - start
    print(f"done in {elapsed:.1f}s")

    cache = {
        "plant_hash": h,
        "q_diag": list(q_diag),
        "r_diag": list(r_diag),
        "K": gains.K.tolist(),
        "tau1_max": gains.tau1_max,
        "tau2_max": gains.tau2_max,
        "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = cache_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, path)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
