"""Phase 2, Stage D: LQR full-state-feedback controller.

Uses the linearized plant from linear_model.py (A, B around the upright
equilibrium) and solve_continuous_are to get a state-feedback gain K (2x4).
Control law: tau = -K @ x  (x_ref = [0,0,0,0], so error = x - x_ref = x),
saturated to the URDF's per-joint torque limits.

Note: linear_model.py requires the numpy2-compatible scipy installed via
`pip3 install --user --upgrade scipy` (the apt one is ABI-broken against
numpy 2.x on this machine -- see private/기획서 env notes).
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from scipy.linalg import solve_continuous_are

from linear_model import DoublePendulum, linearize


@dataclass
class LQRGains:
    K: np.ndarray  # (2, 4)
    tau1_max: float = 60.0
    tau2_max: float = 30.0


def lqr_gain(A, B, Q, R) -> np.ndarray:
    P = solve_continuous_are(A, B, Q, R)
    K = np.linalg.solve(R, B.T @ P)
    return K


def design_lqr(q_diag=(50.0, 50.0, 5.0, 5.0), r_diag=(0.05, 0.05), params=None) -> LQRGains:
    pend = DoublePendulum(params)
    A, B = linearize(pend)
    Q = np.diag(q_diag)
    R = np.diag(r_diag)
    K = lqr_gain(A, B, Q, R)
    return LQRGains(K=K)


def lqr_torque(gains: LQRGains, q1, q2, q1d, q2d):
    x = np.array([q1, q2, q1d, q2d])
    tau = -gains.K @ x
    tau1 = float(max(-gains.tau1_max, min(gains.tau1_max, tau[0])))
    tau2 = float(max(-gains.tau2_max, min(gains.tau2_max, tau[1])))
    return tau1, tau2


if __name__ == "__main__":
    gains = design_lqr()
    print("K =\n", gains.K)
    # sanity: small tilt should produce a small restoring torque, sign
    # pointing back toward q=0
    tau1, tau2 = lqr_torque(gains, np.deg2rad(5.0), 0.0, 0.0, 0.0)
    print(f"tau at q1=5deg tilt: tau1={tau1:.3f} tau2={tau2:.3f} (tau1 should be negative)")
