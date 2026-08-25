"""Phase 2, Stage C: nonlinear dynamics model + numerical linearization
around the upright equilibrium, for LQR gain design.

The nonlinear equations of motion are the same Lagrangian-derived model
used by the original (pre-ROS2) matplotlib simulator at the project root
(`dynamics.py`), ported here verbatim. REFACTOR-001: PendulumParams no
longer hardcodes its own copy of m1/m2/L1/L2/damping/g -- by default it
loads the same double_pendulum_description/config/plant_params.yaml that
double_pendulum.urdf.xacro reads directly, so the offline LQR design and
the simulated plant can never independently drift out of sync (that was
exactly the risk SKILL-CONTROL-MODEL-CONSISTENCY existed to guard
against as a remembered rule -- see harness/skills/retired/). Coordinate
convention:
    q1 = link1 absolute angle from vertical (0 = upright)
    q2 = link2 angle relative to link1 (0 = also upright / in line)
Fully actuated: both tau1, tau2 are control inputs (unlike the underactuated
acrobot/pendubot variants explored earlier, which are out of scope for the
MVP -- see project_plan.md section 2.1).
"""
from __future__ import annotations

import numpy as np
import sympy as sp
from dataclasses import dataclass

from plant_params import load_plant_params


@dataclass
class PendulumParams:
    m1: float
    m2: float
    L1: float
    L2: float
    b1: float
    b2: float
    g: float

    @classmethod
    def from_plant_dict(cls, d: dict) -> "PendulumParams":
        # joint_damping1/2 in plant_params.yaml is the same physical
        # quantity this dataclass calls b1/b2 (viscous joint damping) --
        # named to match the URDF/xacro side, mapped here on load.
        return cls(
            m1=d["m1"], m2=d["m2"], L1=d["L1"], L2=d["L2"],
            b1=d["joint_damping1"], b2=d["joint_damping2"], g=d["g"],
        )

    @classmethod
    def load(cls) -> "PendulumParams":
        return cls.from_plant_dict(load_plant_params())

    def as_tuple(self):
        Lc1, Lc2 = self.L1 / 2.0, self.L2 / 2.0
        I1 = (self.m1 * self.L1 ** 2) / 12.0
        I2 = (self.m2 * self.L2 ** 2) / 12.0
        return (self.m1, self.m2, self.L1, self.L2, Lc1, Lc2,
                I1, I2, self.b1, self.b2, self.g)


def _derive_symbolic():
    """Euler-Lagrange derivation -> qdd = f(q, qd, tau, params). Same
    derivation as the original project's dynamics.py."""
    t = sp.symbols("t")
    m1, m2, L1, L2, Lc1, Lc2, I1, I2, b1, b2, g = sp.symbols(
        "m1 m2 L1 L2 Lc1 Lc2 I1 I2 b1 b2 g", positive=True
    )
    tau1, tau2 = sp.symbols("tau1 tau2")

    q1 = sp.Function("q1")(t)
    q2 = sp.Function("q2")(t)
    q1d, q2d = sp.diff(q1, t), sp.diff(q2, t)

    x1 = Lc1 * sp.sin(q1)
    y1 = Lc1 * sp.cos(q1)
    xj = L1 * sp.sin(q1)
    yj = L1 * sp.cos(q1)
    x2 = xj + Lc2 * sp.sin(q1 + q2)
    y2 = yj + Lc2 * sp.cos(q1 + q2)

    x1d, y1d = sp.diff(x1, t), sp.diff(y1, t)
    x2d, y2d = sp.diff(x2, t), sp.diff(y2, t)

    T = (sp.Rational(1, 2) * m1 * (x1d**2 + y1d**2) + sp.Rational(1, 2) * I1 * q1d**2
         + sp.Rational(1, 2) * m2 * (x2d**2 + y2d**2) + sp.Rational(1, 2) * I2 * (q1d + q2d) ** 2)
    V = m1 * g * y1 + m2 * g * y2
    Lg = sp.simplify(T - V)

    eqs = []
    for q, qd, tau, b in [(q1, q1d, tau1, b1), (q2, q2d, tau2, b2)]:
        dL_dqd = sp.diff(Lg, qd)
        ddt_dL_dqd = sp.diff(dL_dqd, t)
        dL_dq = sp.diff(Lg, q)
        eqs.append(sp.Eq(ddt_dL_dqd - dL_dq + b * qd, tau))

    q1_s, q2_s, q1d_s, q2d_s, q1dd_s, q2dd_s = sp.symbols("q1 q2 q1d q2d q1dd q2dd")
    subs_map = {
        sp.diff(q1, t, 2): q1dd_s, sp.diff(q2, t, 2): q2dd_s,
        q1d: q1d_s, q2d: q2d_s,
        q1: q1_s, q2: q2_s,
    }
    eqs = [sp.Eq(sp.expand(eq.lhs.subs(subs_map)), eq.rhs) for eq in eqs]

    sol = sp.solve(eqs, [q1dd_s, q2dd_s], dict=True)[0]
    qdd1_expr = sp.simplify(sol[q1dd_s])
    qdd2_expr = sp.simplify(sol[q2dd_s])

    params_syms = (m1, m2, L1, L2, Lc1, Lc2, I1, I2, b1, b2, g)
    f_qdd = sp.lambdify((q1_s, q2_s, q1d_s, q2d_s, tau1, tau2, *params_syms),
                        [qdd1_expr, qdd2_expr], modules="numpy", cse=True)
    return f_qdd


_forward_dynamics_cache = None


def get_forward_dynamics():
    global _forward_dynamics_cache
    if _forward_dynamics_cache is None:
        _forward_dynamics_cache = _derive_symbolic()
    return _forward_dynamics_cache


class DoublePendulum:
    def __init__(self, params: PendulumParams | None = None):
        # no hardcoded fallback default -- if plant_params.yaml can't be
        # loaded, this raises loudly instead of silently running against
        # numbers that might not match what's actually spawned in Gazebo.
        self.params = params or PendulumParams.load()
        self._f_qdd = get_forward_dynamics()
        self._p = self.params.as_tuple()

    def accel(self, q1, q2, q1d, q2d, tau1, tau2):
        qdd1, qdd2 = self._f_qdd(q1, q2, q1d, q2d, tau1, tau2, *self._p)
        return float(qdd1), float(qdd2)

    def f(self, x, u):
        """x = [q1,q2,q1d,q2d], u = [tau1,tau2] -> xdot (4,)"""
        q1, q2, q1d, q2d = x
        tau1, tau2 = u
        qdd1, qdd2 = self.accel(q1, q2, q1d, q2d, tau1, tau2)
        return np.array([q1d, q2d, qdd1, qdd2])


def linearize(pend: DoublePendulum, x_eq=(0.0, 0.0, 0.0, 0.0), u_eq=(0.0, 0.0),
              eps_x=1e-6, eps_u=1e-6):
    """Central-difference Jacobian of f(x,u) around (x_eq, u_eq).
    Returns A (4x4), B (4x2)."""
    x_eq = np.array(x_eq, dtype=float)
    u_eq = np.array(u_eq, dtype=float)
    n, m = 4, 2

    A = np.zeros((n, n))
    for i in range(n):
        dx = np.zeros(n)
        dx[i] = eps_x
        f_plus = pend.f(x_eq + dx, u_eq)
        f_minus = pend.f(x_eq - dx, u_eq)
        A[:, i] = (f_plus - f_minus) / (2 * eps_x)

    B = np.zeros((n, m))
    for i in range(m):
        du = np.zeros(m)
        du[i] = eps_u
        f_plus = pend.f(x_eq, u_eq + du)
        f_minus = pend.f(x_eq, u_eq - du)
        B[:, i] = (f_plus - f_minus) / (2 * eps_u)

    return A, B


def controllability_matrix(A, B):
    n = A.shape[0]
    cols = [B]
    Ak = np.eye(n)
    for _ in range(1, n):
        Ak = A @ Ak
        cols.append(Ak @ B)
    return np.hstack(cols)


if __name__ == "__main__":
    pend = DoublePendulum()
    a1, a2 = pend.accel(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    print(f"upright equilibrium check: qdd1={a1:.6e}, qdd2={a2:.6e} (should both be ~0)")

    A, B = linearize(pend)
    print("A =\n", A)
    print("B =\n", B)
    Wc = controllability_matrix(A, B)
    rank = np.linalg.matrix_rank(Wc)
    print(f"controllability matrix rank = {rank} / {A.shape[0]} "
          f"({'controllable' if rank == A.shape[0] else 'NOT fully controllable'})")
