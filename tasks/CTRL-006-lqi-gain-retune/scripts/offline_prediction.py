#!/usr/bin/env python3
"""PHYS-002: offline (no Gazebo) prediction arm.

Reuses autotune_lqr.py's simulate_closed_loop verbatim (nonlinear plant
RHS via DoublePendulum.accel, RK4, same anti-windup clamp) -- NOT a new
simulation -- driven by the exact currently-cached LQI gain (same
load_cached_gains as the real node and the physics-only harness) and the
plant's real current PendulumParams()/plant_params.yaml, deterministic
(no repeats needed: same inputs always produce the same trajectory).

This is the "offline model prediction" arm of PHYS-002's three-way
comparison. Historically this number was cited narratively in
private/roadmap.md as "0.63s" from an earlier ad-hoc search run; this
script reproduces it directly and reproducibly against the ACTUAL
deployed cached gain, rather than re-citing that narrative figure.

Usage:
    offline_prediction.py --scenario nominal_balance --output /tmp/offline_result.json
"""
import argparse
import json
import os
import sys
import time

_EVAL_SCRIPTS = os.path.expanduser("~/agentic_double_pendulum/src/double_pendulum_eval/scripts")
_EVAL_DIR = os.path.expanduser("~/agentic_double_pendulum/src/double_pendulum_eval")
_CONTROL_INSTALL = os.path.expanduser(
    "~/agentic_double_pendulum/install/double_pendulum_control/lib/double_pendulum_control"
)
sys.path.insert(0, _CONTROL_INSTALL)
sys.path.insert(0, _EVAL_SCRIPTS)
sys.path.insert(0, _EVAL_DIR)

# Same import-order note as closed_loop_physics_only_runner.py: lqr_node
# must be imported before autotune_lqr, whose own sys.path.insert would
# otherwise shadow the install/ copy (the only one with a gain cache).
from lqr_node import load_cached_gains  # noqa: E402
from linear_model import DoublePendulum  # noqa: E402
from autotune_lqr import load_scenario, simulate_closed_loop  # noqa: E402
from metrics import compute_metrics, check_acceptance  # noqa: E402

Q_DIAG = (187.0706, 174.4019, 50.4355, 3.2031, 0.0059, 11.0445)  # CTRL-006 re-tuned
R_DIAG = (0.0106, 0.0822)  # CTRL-006 re-tuned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="nominal_balance")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    gains = load_cached_gains(Q_DIAG, R_DIAG)
    pend = DoublePendulum()  # loads PendulumParams.load() -> current plant_params.yaml

    t, q1, q2, tau1, tau2 = simulate_closed_loop(pend, gains.K, scenario, dt=0.01)

    event_t = float(scenario["settle_time_before_s"])
    band_deg = float(scenario.get("settle_band_deg", 1.0))
    metrics = compute_metrics(t, q1, q2, tau1, tau2, event_t, settle_band_deg=band_deg)
    passed, failures = check_acceptance(metrics, scenario["acceptance"])

    result = {
        "scenario": scenario["name"],
        "controller": "lqr_offline_nonlinear_rk4_prediction",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "deterministic (no ROS2, no Gazebo) -- reuses autotune_lqr.simulate_closed_loop "
                "verbatim with the actual cached K and current plant_params.yaml",
        "metrics": metrics.to_dict(),
        "acceptance": scenario["acceptance"],
        "passed": passed,
        "failures": failures,
        "t": t,
        "q1": q1,
        "q2": q2,
        "tau1": tau1,
        "tau2": tau2,
    }

    print(f"=== offline prediction: {'PASS' if passed else 'FAIL'} ===")
    print(json.dumps(metrics.to_dict(), indent=2))
    if failures:
        print("failures:", failures)

    tmp = args.output + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=2)
    os.replace(tmp, args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
