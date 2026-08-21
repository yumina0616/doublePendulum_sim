"""Phase 2, Stage D: LQR full-state-feedback controller, with integral
action (LQI).

Uses the linearized plant from linear_model.py (A, B around the upright
equilibrium), augments it with an integral state per actuated joint
(qi1 = integral of q1, qi2 = integral of q2) so the closed loop can drive
steady-state error to zero even under small model mismatch between the
linearization and Gazebo's actual physics -- pure state feedback (no
integral) was found to settle a few degrees off zero in real Gazebo tests
even though it looked fine offline (see private/roadmap.md, 2026-08-20).

Augmented state: x_aug = [q1, q2, q1d, q2d, qi1, qi2]  (6,)
Augmented dynamics: x_aug_dot = A_aug @ x_aug + B_aug @ u, where the extra
two rows are d(qi)/dt = [q1, q2] (only q1, q2 feed the integrators, not
their derivatives).

Control law: tau = -K @ x_aug, saturated to the URDF's per-joint torque
limits.

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
    K: np.ndarray  # (2, 6)
    tau1_max: float = 60.0
    tau2_max: float = 30.0


def lqr_gain(A, B, Q, R) -> np.ndarray:
    P = solve_continuous_are(A, B, Q, R)
    K = np.linalg.solve(R, B.T @ P)
    return K


def augment_with_integral(A, B):
    """A (4,4), B (4,2) -> A_aug (6,6), B_aug (6,2). Integral states track
    q1, q2 (the first two entries of the state)."""
    n, m = A.shape[0], B.shape[1]
    C = np.zeros((m, n))
    C[0, 0] = 1.0  # qi1_dot = q1
    C[1, 1] = 1.0  # qi2_dot = q2

    A_aug = np.zeros((n + m, n + m))
    A_aug[:n, :n] = A
    A_aug[n:, :n] = C

    B_aug = np.zeros((n + m, m))
    B_aug[:n, :] = B
    return A_aug, B_aug


def design_lqr(q_diag=(50.0, 50.0, 5.0, 5.0, 10.0, 10.0), r_diag=(0.05, 0.05),
                params=None) -> LQRGains:
    pend = DoublePendulum(params)
    A, B = linearize(pend)
    A_aug, B_aug = augment_with_integral(A, B)
    Q = np.diag(q_diag)
    R = np.diag(r_diag)
    K = lqr_gain(A_aug, B_aug, Q, R)
    return LQRGains(K=K)


def lqr_torque(gains: LQRGains, q1, q2, q1d, q2d, qi1, qi2):
    x = np.array([q1, q2, q1d, q2d, qi1, qi2])
    tau = -gains.K @ x
    tau1 = float(max(-gains.tau1_max, min(gains.tau1_max, tau[0])))
    tau2 = float(max(-gains.tau2_max, min(gains.tau2_max, tau[1])))
    return tau1, tau2


if __name__ == "__main__":
    gains = design_lqr()
    print("K =\n", gains.K)
    # sanity: small tilt should produce a small restoring torque, sign
    # pointing back toward q=0
    tau1, tau2 = lqr_torque(gains, np.deg2rad(5.0), 0.0, 0.0, 0.0, 0.0, 0.0)
    print(f"tau at q1=5deg tilt: tau1={tau1:.3f} tau2={tau2:.3f} (tau1 should be negative)")
