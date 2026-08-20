"""Phase 3: pure metric functions over a recorded time series.

No ROS/Gazebo dependency on purpose -- unit-testable standalone, and
reusable from run_experiment.py. A "recording" is just parallel arrays:
    t: (N,) seconds since recording start
    q1, q2: (N,) rad
    tau1, tau2: (N,) N*m (last commanded value at/around each sample time)

Convention (matches the rest of the project): target is q1=q2=0 (upright).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict


def settling_time(t, q, event_t: float, band_deg: float = 1.0) -> float:
    """Time (relative to event_t) after which |q| stays within band_deg for
    the rest of the recording. Returns inf if it never does."""
    band = math.radians(band_deg)
    n = len(t)
    for i in range(n):
        if t[i] < event_t:
            continue
        if all(abs(q[j]) <= band for j in range(i, n)):
            return t[i] - event_t
    return float("inf")


def overshoot_deg(q, event_t=None, t=None) -> float:
    """Max |angle| in degrees, optionally restricted to samples at/after
    event_t."""
    if event_t is not None and t is not None:
        vals = [abs(q[i]) for i in range(len(t)) if t[i] >= event_t]
    else:
        vals = [abs(v) for v in q]
    return math.degrees(max(vals)) if vals else 0.0


def rms_error(q, event_t=None, t=None) -> float:
    if event_t is not None and t is not None:
        vals = [q[i] for i in range(len(t)) if t[i] >= event_t]
    else:
        vals = list(q)
    if not vals:
        return 0.0
    return math.sqrt(sum(v * v for v in vals) / len(vals))


def max_abs(x) -> float:
    return max((abs(v) for v in x), default=0.0)


@dataclass
class RunMetrics:
    stable: bool
    settling_time_q1_s: float
    settling_time_q2_s: float
    overshoot_q1_deg: float
    overshoot_q2_deg: float
    rms_error_q1_rad: float
    rms_error_q2_rad: float
    max_abs_tau1_nm: float
    max_abs_tau2_nm: float
    final_q1_deg: float
    final_q2_deg: float

    def to_dict(self):
        return asdict(self)


FAIL_ANGLE_DEG = 90.0  # beyond this, consider the pendulum "fallen" -> unstable


def compute_metrics(t, q1, q2, tau1, tau2, event_t: float,
                     settle_band_deg: float = 1.0) -> RunMetrics:
    max_q1 = overshoot_deg(q1)
    max_q2 = overshoot_deg(q2)
    stable = max_q1 < FAIL_ANGLE_DEG and max_q2 < FAIL_ANGLE_DEG

    return RunMetrics(
        stable=stable,
        settling_time_q1_s=settling_time(t, q1, event_t, settle_band_deg),
        settling_time_q2_s=settling_time(t, q2, event_t, settle_band_deg),
        overshoot_q1_deg=overshoot_deg(q1, event_t, t),
        overshoot_q2_deg=overshoot_deg(q2, event_t, t),
        rms_error_q1_rad=rms_error(q1, event_t, t),
        rms_error_q2_rad=rms_error(q2, event_t, t),
        max_abs_tau1_nm=max_abs(tau1),
        max_abs_tau2_nm=max_abs(tau2),
        final_q1_deg=math.degrees(q1[-1]) if q1 else 0.0,
        final_q2_deg=math.degrees(q2[-1]) if q2 else 0.0,
    )


def check_acceptance(metrics: RunMetrics, acceptance: dict) -> tuple[bool, list[str]]:
    """acceptance is a dict like {"stable": true, "settling_time_s": {"max": 3.0}, ...}.
    Returns (passed, list_of_failure_reasons)."""
    m = metrics.to_dict()
    failures = []

    if "stable" in acceptance and bool(m["stable"]) != bool(acceptance["stable"]):
        failures.append(f"stable={m['stable']} (expected {acceptance['stable']})")

    for key, rule in acceptance.items():
        if key == "stable" or not isinstance(rule, dict):
            continue
        if key not in m:
            continue
        val = m[key]
        if "max" in rule and val > rule["max"]:
            failures.append(f"{key}={val:.4f} exceeds max {rule['max']}")
        if "min" in rule and val < rule["min"]:
            failures.append(f"{key}={val:.4f} below min {rule['min']}")

    return (len(failures) == 0), failures


if __name__ == "__main__":
    # self-test with synthetic data: a decaying oscillation settling by t=3s
    import math as _m
    dt = 0.01
    N = 800
    t = [i * dt for i in range(N)]
    event_t = 1.0
    q1 = []
    for ti in t:
        if ti < event_t:
            q1.append(0.0)
        else:
            tau = ti - event_t
            q1.append(_m.radians(15.0) * _m.exp(-tau / 0.5) * _m.cos(2 * _m.pi * 2 * tau))
    q2 = [0.0] * N
    tau1 = [10.0 if abs(v) > 1e-6 else 0.0 for v in q1]
    tau2 = [0.0] * N

    metrics = compute_metrics(t, q1, q2, tau1, tau2, event_t)
    print(metrics.to_dict())

    acceptance = {
        "stable": True,
        "settling_time_q1_s": {"max": 3.0},
        "overshoot_q1_deg": {"max": 20.0},
        "max_abs_tau1_nm": {"max": 60.0},
    }
    passed, failures = check_acceptance(metrics, acceptance)
    print(f"passed={passed} failures={failures}")
    assert passed, "self-test acceptance check should pass"
    assert metrics.settling_time_q1_s < 3.0
    print("SELF_TEST_OK")
