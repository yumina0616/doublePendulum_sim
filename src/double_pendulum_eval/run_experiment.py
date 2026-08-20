#!/usr/bin/env python3
"""Phase 3: automated experiment runner.

Records /joint_states + /effort_controller/commands, fires a disturbance
pulse partway through (same repeat-publish approach as disturbance.py, to
reliably win the topic race against an active controller node -- see
disturbance.py's docstring), computes metrics.py stats, checks them against
the scenario's acceptance criteria, and writes a result.json. Exits 0 on
pass, 1 on fail, matching CI conventions.

Assumes Gazebo + a controller node (PD or LQR) are already running (this
script does not launch them -- run/launch those yourself first, same as
disturbance.py).

    ros2 run double_pendulum_eval run_experiment.py --scenario nominal_balance
    ros2 run double_pendulum_eval run_experiment.py --scenario impulse_disturbance \
        --output /tmp/impulse_result.json --controller lqr
"""
import argparse
import json
import os
import time

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from metrics import compute_metrics, check_acceptance

JOINT_ORDER = ["joint1", "joint2"]


def find_scenario_path(name: str) -> str:
    # look next to this source file first (works with --symlink-install
    # without a rebuild), then fall back to the installed share/ copy.
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios", f"{name}.yaml")
    if os.path.isfile(local):
        return local
    share = os.path.join(get_package_share_directory("double_pendulum_eval"), "scenarios", f"{name}.yaml")
    return share


class ExperimentRunner(Node):
    def __init__(self, scenario: dict, controller_name: str, output_path: str):
        super().__init__("run_experiment")
        self.scenario = scenario
        self.controller_name = controller_name
        self.output_path = output_path

        d = scenario["disturbance"]
        self.pulse_tau = (float(d.get("tau1", 0.0)), float(d.get("tau2", 0.0)))
        self.pulse_duration = float(d.get("pulse_duration", 0.3))
        self.pulse_rate_hz = float(d.get("rate_hz", 500.0))
        self.settle_before = float(scenario["settle_time_before_s"])
        self.total_duration = float(scenario["total_duration_s"])
        self.settle_band_deg = float(scenario.get("settle_band_deg", 1.0))

        self.t0 = None
        self.rec_t, self.rec_q1, self.rec_q2 = [], [], []
        self.rec_tau_t, self.rec_tau1, self.rec_tau2 = [], [], []
        self._pulse_active = False
        self._pulse_released = False
        self._last_pulse_pub = 0.0
        self._finished = False

        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 50)
        self.create_subscription(Float64MultiArray, "/effort_controller/commands", self._on_effort, 50)
        self.cmd_pub = self.create_publisher(Float64MultiArray, "/effort_controller/commands", 10)

        self.create_timer(1.0 / max(self.pulse_rate_hz, 50.0), self._on_tick)
        self.get_logger().info(
            f"Scenario '{scenario['name']}': settle {self.settle_before}s, "
            f"pulse {self.pulse_tau} for {self.pulse_duration}s, "
            f"total {self.total_duration}s, controller={controller_name}"
        )

    def _now_s(self) -> float:
        if self.t0 is None:
            self.t0 = self.get_clock().now()
        return (self.get_clock().now() - self.t0).nanoseconds / 1e9

    def _on_joint_states(self, msg: JointState):
        try:
            idx = [msg.name.index(j) for j in JOINT_ORDER]
        except ValueError:
            return
        t = self._now_s()
        self.rec_t.append(t)
        self.rec_q1.append(msg.position[idx[0]])
        self.rec_q2.append(msg.position[idx[1]])

    def _on_effort(self, msg: Float64MultiArray):
        if len(msg.data) < 2:
            return
        t = self._now_s()
        self.rec_tau_t.append(t)
        self.rec_tau1.append(msg.data[0])
        self.rec_tau2.append(msg.data[1])

    def _on_tick(self):
        if self._finished:
            return
        t = self._now_s()

        in_pulse_window = self.settle_before <= t < (self.settle_before + self.pulse_duration)
        if in_pulse_window:
            msg = Float64MultiArray()
            msg.data = list(self.pulse_tau)
            self.cmd_pub.publish(msg)
            self._pulse_active = True
        elif self._pulse_active and not self._pulse_released:
            msg = Float64MultiArray()
            msg.data = [0.0, 0.0]
            self.cmd_pub.publish(msg)
            self._pulse_released = True

        if t >= self.total_duration:
            self._finished = True
            self._finalize()

    def _finalize(self):
        event_t = self.settle_before
        metrics = compute_metrics(
            self.rec_t, self.rec_q1, self.rec_q2,
            self.rec_tau1, self.rec_tau2, event_t,
            settle_band_deg=self.settle_band_deg,
        )
        passed, failures = check_acceptance(metrics, self.scenario["acceptance"])

        result = {
            "scenario": self.scenario["name"],
            "controller": self.controller_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "n_samples_joint_states": len(self.rec_t),
            "n_samples_effort": len(self.rec_tau1),
            "metrics": metrics.to_dict(),
            "acceptance": self.scenario["acceptance"],
            "passed": passed,
            "failures": failures,
        }

        os.makedirs(os.path.dirname(os.path.abspath(self.output_path)) or ".", exist_ok=True)
        with open(self.output_path, "w") as f:
            json.dump(result, f, indent=2)

        status = "PASS" if passed else "FAIL"
        self.get_logger().info(f"=== {status} === {self.scenario['name']} -> {self.output_path}")
        self.get_logger().info(json.dumps(metrics.to_dict(), indent=2))
        if failures:
            self.get_logger().warn(f"failures: {failures}")

        self._exit_code = 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="nominal_balance")
    parser.add_argument("--controller", default="unspecified",
                         help="label only (pd/lqr), for the result.json -- doesn't launch anything")
    parser.add_argument("--output", default=None)
    args, _ = parser.parse_known_args()

    scenario_path = find_scenario_path(args.scenario)
    with open(scenario_path) as f:
        scenario = yaml.safe_load(f)

    output_path = args.output or f"/tmp/{args.scenario}_result.json"

    rclpy.init()
    node = ExperimentRunner(scenario, args.controller, output_path)
    try:
        while rclpy.ok() and not node._finished:
            rclpy.spin_once(node, timeout_sec=0.05)
    except KeyboardInterrupt:
        pass
    exit_code = getattr(node, "_exit_code", 1)
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
