#!/usr/bin/env python3
"""Phase 3: offline LQI weight search (no Gazebo/ROS2 needed).

The slow part of LQR gain design is the sympy symbolic derivation of the
plant dynamics -- but that only produces A/B (the linearization), which
does NOT depend on Q/R. So instead of restarting Gazebo + re-deriving the
dynamics for every candidate weight set (~90s each, what we were doing by
hand), this derives the dynamics ONCE, then simulates the closed loop in
pure Python (fixed-step RK4) for many candidates via differential_evolution
-- mirroring the original (pre-ROS2) project's fast-search / precise-verify
split.

Two things this had to get right to actually predict real Gazebo behavior
(see private/roadmap.md, 2026-08-20 for how each was found):
  1. The disturbance must be modeled as a genuine external push -- additive
     to the dynamics, not routed through (or overriding) the actuator
     command -- matching Gazebo's ApplyLinkWrench-based
     wrench_disturbance.py, not the retired topic-race approach.
  2. The controller includes integral action (see lqr_controller.py's
     augment_with_integral): pure state feedback looked perfect offline but
     left a persistent few-degree offset in real Gazebo from small
     model/physics-engine mismatch, which only an integral term fixes.

Run:
    python3 autotune_lqr.py --scenario nominal_balance

Then verify the winning weights for real in Gazebo:
    bash run_clean_experiment.sh lqr nominal_balance -- --ros-args \
        -p q1d:=<...> -p q2d:=<...> -p qi1:=<...> -p qi2:=<...> \
        -p r1:=<...> -p r2:=<...>
"""
import argparse
import os
import sys
import time

import numpy as np
import yaml
from scipy.linalg import solve_continuous_are
from scipy.optimize import differential_evolution

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "double_pendulum_control"))  # linear_model.py, lqr_controller.py live here
sys.path.insert(0, os.path.join(_HERE, ".."))  # metrics.py lives here
from linear_model import DoublePendulum, PendulumParams, linearize  # noqa: E402
from lqr_controller import augment_with_integral  # noqa: E402
from metrics import compute_metrics, check_acceptance  # noqa: E402

TAU1_MAX = 60.0
TAU2_MAX = 30.0
QI_MAX = 3.0  # matches lqr_node.py's anti-windup clamp on the integral state

BOUNDS = [
    (1.0, 200.0),   # q1
    (1.0, 200.0),   # q2
    (0.1, 60.0),    # q1d
    (0.1, 60.0),    # q2d
    (0.0, 15.0),    # qi1
    (0.0, 15.0),    # qi2
    (0.01, 1.0),    # r1
    (0.01, 1.0),    # r2
]
W_LABELS = ["q1", "q2", "q1d", "q2d", "qi1", "qi2", "r1", "r2"]


def load_scenario(name: str) -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scenarios", f"{name}.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def simulate_closed_loop(pend: DoublePendulum, K: np.ndarray, scenario: dict, dt: float = 0.01):
    """State integrated here is the augmented [q1,q2,q1d,q2d,qi1,qi2] (6,)."""
    d = scenario["disturbance"]
    # "link" tells you which joint the push acts on; torque_y maps to
    # tau1 for link1, tau2 for link2 (matches wrench_disturbance.py).
    tau_pulse = (float(d.get("torque_y", 0.0)), 0.0) if d.get("link", "link1") == "link1" \
        else (0.0, float(d.get("torque_y", 0.0)))
    pulse_start = float(scenario["settle_time_before_s"])
    pulse_end = pulse_start + float(d.get("pulse_duration", 0.3))
    total = float(scenario["total_duration_s"])

    def control(x):
        """Controller output only -- always active, saturated to actuator
        limits (what the motor can actually deliver)."""
        tau = -K @ x
        tau[0] = np.clip(tau[0], -TAU1_MAX, TAU1_MAX)
        tau[1] = np.clip(tau[1], -TAU2_MAX, TAU2_MAX)
        return tau

    def disturbance(t):
        """External push -- additive to the dynamics, NOT routed through
        the actuator. Matches wrench_disturbance.py / ApplyLinkWrench."""
        if pulse_start <= t < pulse_end:
            return np.array(tau_pulse)
        return np.zeros(2)

    def rhs(t, x, u_ctrl, u_dist):
        q1, q2, q1d, q2d, qi1, qi2 = x
        qdd1, qdd2 = pend.accel(q1, q2, q1d, q2d,
                                 u_ctrl[0] + u_dist[0], u_ctrl[1] + u_dist[1])
        return np.array([q1d, q2d, qdd1, qdd2, q1, q2])

    n = int(round(total / dt)) + 1
    t_hist = np.empty(n)
    q1_hist = np.empty(n)
    q2_hist = np.empty(n)
    tau1_hist = np.empty(n)
    tau2_hist = np.empty(n)

    x = np.zeros(6)
    for i in range(n):
        t = i * dt
        u_ctrl = control(x)
        u_dist = disturbance(t)
        t_hist[i], q1_hist[i], q2_hist[i] = t, x[0], x[1]
        tau1_hist[i], tau2_hist[i] = u_ctrl[0], u_ctrl[1]

        k1 = rhs(t, x, u_ctrl, u_dist)
        k2 = rhs(t + dt / 2, x + dt / 2 * k1, u_ctrl, u_dist)
        k3 = rhs(t + dt / 2, x + dt / 2 * k2, u_ctrl, u_dist)
        k4 = rhs(t + dt, x + dt * k3, u_ctrl, u_dist)
        x = x + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
        # anti-windup clamp on the integral states, matching lqr_node.py
        x[4] = np.clip(x[4], -QI_MAX, QI_MAX)
        x[5] = np.clip(x[5], -QI_MAX, QI_MAX)

    return t_hist.tolist(), q1_hist.tolist(), q2_hist.tolist(), \
        tau1_hist.tolist(), tau2_hist.tolist()


def make_cost_fn(pend, A_aug, B_aug, scenario):
    event_t = float(scenario["settle_time_before_s"])
    band_deg = float(scenario.get("settle_band_deg", 1.0))
    total = float(scenario["total_duration_s"])

    def cost(v):
        q1, q2, q1d, q2d, qi1, qi2, r1, r2 = v
        Q = np.diag([q1, q2, q1d, q2d, qi1, qi2])
        R = np.diag([r1, r2])
        try:
            P = solve_continuous_are(A_aug, B_aug, Q, R)
            K = np.linalg.solve(R, B_aug.T @ P)
        except Exception:
            return 1e6

        t, qq1, qq2, tau1, tau2 = simulate_closed_loop(pend, K, scenario)
        m = compute_metrics(t, qq1, qq2, tau1, tau2, event_t, settle_band_deg=band_deg)

        st1 = min(m.settling_time_q1_s, 2 * total)
        st2 = min(m.settling_time_q2_s, 2 * total)
        penalty = 0.0 if m.stable else 1000.0
        return (st1 + st2
                + 0.3 * (m.overshoot_q1_deg + m.overshoot_q2_deg)
                + 5.0 * (m.rms_error_q1_rad + m.rms_error_q2_rad)
                + 2.0 * (abs(m.final_q1_deg) + abs(m.final_q2_deg))
                + penalty)

    return cost


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="nominal_balance")
    parser.add_argument("--maxiter", type=int, default=40)
    parser.add_argument("--popsize", type=int, default=15)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    print(f"Scenario: {scenario['name']}")

    print("Deriving plant dynamics (sympy, one-time cost, ~1 min)...")
    t0 = time.time()
    pend = DoublePendulum(PendulumParams())
    A, B = linearize(pend)
    A_aug, B_aug = augment_with_integral(A, B)
    print(f"  done in {time.time() - t0:.1f}s")
    print("A_aug =\n", A_aug)
    print("B_aug =\n", B_aug)

    cost_fn = make_cost_fn(pend, A_aug, B_aug, scenario)

    print(f"\nSearching {W_LABELS} via differential_evolution "
          f"(maxiter={args.maxiter}, popsize={args.popsize})...")
    t0 = time.time()
    result = differential_evolution(
        cost_fn, BOUNDS, maxiter=args.maxiter, popsize=args.popsize,
        seed=args.seed, tol=1e-4, mutation=(0.4, 1.2), recombination=0.7,
        polish=True, updating="deferred", workers=1,
    )
    print(f"  done in {time.time() - t0:.1f}s, best cost={result.fun:.4f}")

    v = result.x
    weights = dict(zip(W_LABELS, v.tolist()))
    print("\nBest weights:")
    for k, val in weights.items():
        print(f"  {k} = {val:.4f}")

    q1, q2, q1d, q2d, qi1, qi2, r1, r2 = v
    Q = np.diag([q1, q2, q1d, q2d, qi1, qi2])
    R = np.diag([r1, r2])
    P = solve_continuous_are(A_aug, B_aug, Q, R)
    K = np.linalg.solve(R, B_aug.T @ P)
    print("K =\n", K)

    t, qq1, qq2, tau1, tau2 = simulate_closed_loop(pend, K, scenario)
    event_t = float(scenario["settle_time_before_s"])
    band_deg = float(scenario.get("settle_band_deg", 1.0))
    m = compute_metrics(t, qq1, qq2, tau1, tau2, event_t, settle_band_deg=band_deg)
    passed, failures = check_acceptance(m, scenario["acceptance"])

    print(f"\n=== offline sim result: {'PASS' if passed else 'FAIL'} ===")
    print(m.to_dict())
    if failures:
        print("failures:", failures)

    print("\nVerify for real in Gazebo:")
    print(
        f"  bash run_clean_experiment.sh lqr {args.scenario} -- --ros-args "
        f"-p q1d:={q1d:.3f} -p q2d:={q2d:.3f} -p qi1:={qi1:.3f} -p qi2:={qi2:.3f} "
        f"-p r1:={r1:.4f} -p r2:={r2:.4f}"
    )


if __name__ == "__main__":
    main()
