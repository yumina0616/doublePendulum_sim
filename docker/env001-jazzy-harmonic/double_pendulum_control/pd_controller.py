"""Independent per-joint PD control law (Phase 2, Stage B).

Target is always upright: q1 = q2 = 0 (see double_pendulum.urdf.xacro for
the coordinate convention). Fully actuated MVP: both joints get their own
independent PD law with no cross-coupling term -- this is deliberately the
simplest possible controller, just to validate the ROS2 control loop
end-to-end (gain -> response, overshoot/settling metrics) before Stage C/D
introduce linearization and LQR.
"""
from dataclasses import dataclass


@dataclass
class PDGains:
    kp1: float
    kd1: float
    kp2: float
    kd2: float
    tau1_max: float = 60.0
    tau2_max: float = 30.0


def pd_torque(gains: PDGains, q1: float, q2: float, q1d: float, q2d: float):
    """Returns (tau1, tau2), saturated to the URDF's effort limits."""
    tau1 = -gains.kp1 * q1 - gains.kd1 * q1d
    tau2 = -gains.kp2 * q2 - gains.kd2 * q2d
    tau1 = max(-gains.tau1_max, min(gains.tau1_max, tau1))
    tau2 = max(-gains.tau2_max, min(gains.tau2_max, tau2))
    return tau1, tau2
