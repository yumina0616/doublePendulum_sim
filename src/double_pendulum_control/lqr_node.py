#!/usr/bin/env python3
"""Phase 2 Stage D: LQR controller node, with integral action (LQI).

Full-state feedback (q1,q2,q1d,q2d) toward the upright equilibrium, plus
an integral state per joint (qi1, qi2) so small model-mismatch between the
linearization and Gazebo's actual physics doesn't leave a persistent
steady-state offset (pure state feedback settled a few degrees off zero in
real Gazebo tests -- see private/roadmap.md, 2026-08-20).

    ros2 run double_pendulum_control lqr_node.py
    ros2 run double_pendulum_control lqr_node.py --ros-args \
        -p q1:=100.0 -p q2:=100.0 -p q1d:=10.0 -p q2d:=10.0 \
        -p qi1:=10.0 -p qi2:=10.0 -p r1:=0.05 -p r2:=0.05

REFACTOR-001: gain design (sympy linearization + CARE solve, ~1 min) no
longer runs at every node startup. Instead this loads a gain cache
(lqr_gain_cache.json, written by design_lqr_gains.py) and REFUSES to
start if that cache's plant_hash/q_diag/r_diag don't match the current
plant_params.yaml and requested weights -- run design_lqr_gains.py first
whenever plant_params.yaml or the Q/R weights change. Pass
--auto-design (as a ROS param, see below) to fall back to the old
compute-inline-every-time behavior instead of failing.

    ros2 run double_pendulum_control lqr_node.py --ros-args -p auto_design:=true

Requires double_pendulum_description/spawn.launch.py already running (so
/joint_states and /effort_controller/commands exist).
"""
import json
import os

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from lqr_controller import LQRGains, design_lqr, lqr_torque
from plant_params import load_plant_params, plant_hash

JOINT_ORDER = ["joint1", "joint2"]
CACHE_FILENAME = "lqr_gain_cache.json"


def cache_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CACHE_FILENAME)


def load_cached_gains(q_diag, r_diag) -> LQRGains:
    """Returns the cached LQRGains if the cache exists and matches the
    current plant_params.yaml + requested q_diag/r_diag exactly. Raises
    RuntimeError with a specific, actionable reason otherwise -- never
    silently falls back to a mismatched or missing cache."""
    plant = load_plant_params()
    current_hash = plant_hash(plant)
    path = cache_path()

    if not os.path.isfile(path):
        raise RuntimeError(
            f"no gain cache found at {path}. Run design_lqr_gains.py first "
            f"(current plant_hash={current_hash}), or pass "
            f"-p auto_design:=true to compute inline instead (~1 min)."
        )

    with open(path) as f:
        cache = json.load(f)

    if cache.get("plant_hash") != current_hash:
        raise RuntimeError(
            f"STALE GAIN: plant_params.yaml has changed since this gain was "
            f"designed (cached plant_hash={cache.get('plant_hash')}, current "
            f"plant_hash={current_hash}). Re-run design_lqr_gains.py, or pass "
            f"-p auto_design:=true to compute inline instead (~1 min)."
        )
    if list(cache.get("q_diag", [])) != list(q_diag) or list(cache.get("r_diag", [])) != list(r_diag):
        raise RuntimeError(
            f"gain cache was designed for different Q/R weights "
            f"(cached q_diag={cache.get('q_diag')}, r_diag={cache.get('r_diag')}; "
            f"requested q_diag={list(q_diag)}, r_diag={list(r_diag)}). "
            f"Re-run design_lqr_gains.py with matching --q1/--q2/... flags, "
            f"or pass -p auto_design:=true to compute inline instead (~1 min)."
        )

    return LQRGains(
        K=np.array(cache["K"]),
        tau1_max=cache["tau1_max"],
        tau2_max=cache["tau2_max"],
    )


class LQRControllerNode(Node):
    def __init__(self):
        super().__init__("lqr_controller_node")

        self.declare_parameter("q1", 50.0)
        self.declare_parameter("q2", 50.0)
        self.declare_parameter("q1d", 5.0)
        self.declare_parameter("q2d", 5.0)
        self.declare_parameter("qi1", 10.0)
        self.declare_parameter("qi2", 10.0)
        self.declare_parameter("r1", 0.05)
        self.declare_parameter("r2", 0.05)
        self.declare_parameter("rate_hz", 100.0)
        self.declare_parameter("auto_design", False)
        # simple bounded-integral anti-windup: caps |qi1|, |qi2| directly
        # rather than reasoning about the sign of K's integral columns
        self.declare_parameter("qi_max", 3.0)

        q_diag = (
            self.get_parameter("q1").value,
            self.get_parameter("q2").value,
            self.get_parameter("q1d").value,
            self.get_parameter("q2d").value,
            self.get_parameter("qi1").value,
            self.get_parameter("qi2").value,
        )
        r_diag = (self.get_parameter("r1").value, self.get_parameter("r2").value)
        self.qi_max = self.get_parameter("qi_max").value
        auto_design = self.get_parameter("auto_design").value

        try:
            self.gains = load_cached_gains(q_diag, r_diag)
            self.get_logger().info(f"Loaded cached LQR gain (skipped CARE solve). K =\n{self.gains.K}")
        except RuntimeError as e:
            if not auto_design:
                self.get_logger().error(str(e))
                raise SystemExit(str(e))
            self.get_logger().warn(f"{e}\nauto_design=true -- computing inline instead.")
            self.get_logger().info("Designing LQR gain (linearizing + solving CARE, ~1 min)...")
            self.gains = design_lqr(q_diag=q_diag, r_diag=r_diag)
            self.get_logger().info(f"LQR ready. K =\n{self.gains.K}")

        self._latest = None  # (q1, q2, q1d, q2d)
        self.qi1 = 0.0
        self.qi2 = 0.0
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 10)
        self.cmd_pub = self.create_publisher(Float64MultiArray, "/effort_controller/commands", 10)

        rate_hz = self.get_parameter("rate_hz").value
        self.dt = 1.0 / rate_hz
        self.create_timer(self.dt, self._on_timer)
        # printed unconditionally (not just in the auto_design branch) so
        # run_clean_experiment.sh's existing "LQR ready" log-grep readiness
        # check still fires on the cached-gain fast path too.
        self.get_logger().info("LQR ready.")

    def _on_joint_states(self, msg: JointState):
        try:
            idx = [msg.name.index(j) for j in JOINT_ORDER]
        except ValueError:
            return
        q = [msg.position[i] for i in idx]
        qd = [msg.velocity[i] for i in idx] if msg.velocity else [0.0, 0.0]
        self._latest = (q[0], q[1], qd[0], qd[1])

    def _on_timer(self):
        if self._latest is None:
            return
        q1, q2, q1d, q2d = self._latest

        self.qi1 = max(-self.qi_max, min(self.qi_max, self.qi1 + q1 * self.dt))
        self.qi2 = max(-self.qi_max, min(self.qi_max, self.qi2 + q2 * self.dt))

        tau1, tau2 = lqr_torque(self.gains, q1, q2, q1d, q2d, self.qi1, self.qi2)
        msg = Float64MultiArray()
        msg.data = [tau1, tau2]
        self.cmd_pub.publish(msg)


def main():
    rclpy.init()
    try:
        node = LQRControllerNode()
    except SystemExit:
        rclpy.shutdown()
        raise
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
