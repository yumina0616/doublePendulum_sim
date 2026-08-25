#!/usr/bin/env python3
"""Phase 3: automated experiment runner.

Records /joint_states + /effort_controller/commands, applies a real
external push via Gazebo's ApplyLinkWrench system partway through (see
wrench_disturbance.py -- the controller keeps running and resisting
throughout, unlike the retired approach of racing a pulse against it on
/effort_controller/commands, which briefly blacked the controller out
completely), computes metrics.py stats, checks them against the
scenario's acceptance criteria, and writes a result.json. Exits 0 on
pass, 1 on fail, matching CI conventions.

Assumes Gazebo (with the gz-sim-apply-link-wrench-system plugin loaded --
already in empty_world.sdf) + a controller node (PD or LQR) are already
running (this script does not launch them -- run/launch those yourself
first, or use scripts/run_clean_experiment.sh which does both).

    ros2 run double_pendulum_eval run_experiment.py --scenario nominal_balance
    ros2 run double_pendulum_eval run_experiment.py --scenario impulse_disturbance \
        --output /tmp/impulse_result.json --controller lqr
"""
import argparse
import json
import os
import subprocess
import time
import traceback

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from metrics import compute_metrics, check_acceptance, classify_verdict, VERDICT_INVALID_INFRA, VERDICT_FAIL_HARNESS

JOINT_ORDER = ["joint1", "joint2"]


def find_scenario_path(name: str) -> str:
    # look next to this source file first (works with --symlink-install
    # without a rebuild), then fall back to the installed share/ copy.
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios", f"{name}.yaml")
    if os.path.isfile(local):
        return local
    share = os.path.join(get_package_share_directory("double_pendulum_eval"), "scenarios", f"{name}.yaml")
    return share


def apply_wrench(world: str, link: str, model: str, torque_y: float):
    entity_name = f"{model}::{link}"
    req = (
        f'entity: {{name: "{entity_name}", type: LINK}}, '
        f"wrench: {{torque: {{y: {torque_y}}}}}"
    )
    cmd = ["gz", "topic", "-t", f"/world/{world}/wrench/persistent",
           "-m", "gz.msgs.EntityWrench", "-p", req]
    subprocess.run(cmd, check=True)


def clear_wrench(world: str, link: str, model: str):
    entity_name = f"{model}::{link}"
    req = f'name: "{entity_name}", type: LINK'
    cmd = ["gz", "topic", "-t", f"/world/{world}/wrench/clear",
           "-m", "gz.msgs.Entity", "-p", req]
    subprocess.run(cmd, check=True)


def write_result_json(output_path: str, result: dict):
    """INFRA-003 (partial): atomic write via temp-file + rename, so a
    process killed mid-write (kill -9 during teardown, disk full, etc)
    never leaves a partially-written/corrupt result.json for downstream
    aggregation to trip over."""
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    tmp_path = output_path + f".tmp.{os.getpid()}"
    with open(tmp_path, "w") as f:
        json.dump(result, f, indent=2)
    os.replace(tmp_path, output_path)


def write_infra_failure_result(output_path: str, scenario_name: str, controller_name: str,
                                verdict: str, reason: str):
    """Used for failures that never reach ExperimentRunner._finalize (a
    discovery timeout, an uncaught exception) so the caller (and
    run_repeated_experiment.sh's aggregation) always finds a result.json
    with a verdict field, regardless of which stage failed. Before
    INFRA-001 this path wrote nothing at all, which forced downstream
    tooling to infer infra failure from a missing file instead of reading
    it directly."""
    result = {
        "scenario": scenario_name,
        "controller": controller_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_samples_joint_states": 0,
        "n_samples_effort": 0,
        "metrics": None,
        "acceptance": None,
        "passed": False,
        "failures": [reason],
        "verdict": verdict,
    }
    write_result_json(output_path, result)


class ExperimentRunner(Node):
    def __init__(self, scenario: dict, controller_name: str, output_path: str):
        super().__init__("run_experiment")
        self.scenario = scenario
        self.controller_name = controller_name
        self.output_path = output_path

        d = scenario["disturbance"]
        self.world = d.get("world", "double_pendulum_world")
        self.model = d.get("model", "double_pendulum")
        self.link = d.get("link", "link1")
        self.torque_y = float(d.get("torque_y", 0.0))
        self.pulse_duration = float(d.get("pulse_duration", 0.3))
        self.settle_before = float(scenario["settle_time_before_s"])
        self.total_duration = float(scenario["total_duration_s"])
        self.settle_band_deg = float(scenario.get("settle_band_deg", 1.0))

        self.t0 = None
        self.rec_t, self.rec_q1, self.rec_q2 = [], [], []
        self.rec_tau1, self.rec_tau2 = [], []
        self._pulse_applied = False
        self._pulse_cleared = False
        self._finished = False

        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 50)
        self.create_subscription(Float64MultiArray, "/effort_controller/commands", self._on_effort, 50)

        self.create_timer(0.02, self._on_tick)
        self.get_logger().info(
            f"Scenario '{scenario['name']}': settle {self.settle_before}s, "
            f"push {self.torque_y} N*m on {self.model}::{self.link} for {self.pulse_duration}s, "
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
        self.rec_tau1.append(msg.data[0])
        self.rec_tau2.append(msg.data[1])

    def _on_tick(self):
        if self._finished:
            return
        if not self.rec_t:
            # CTRL-005: _on_tick's 0.02s timer starts firing at node
            # construction, long before /joint_states discovery is
            # guaranteed to have completed. _now_s() lazily sets t0 on its
            # FIRST call -- if that first call came from _on_tick instead
            # of a real _on_joint_states callback, the whole settle/push/
            # total_duration schedule starts counting down from node
            # startup instead of from real data flow, and a slow discovery
            # can burn through the entire scenario before any sample is
            # ever recorded (observed: a run with n_samples_joint_states=0
            # AND n_samples_effort=0 -- not a physics result, an artifact
            # of this race). Don't advance the schedule at all until the
            # first real /joint_states message has set t0 itself.
            return
        t = self._now_s()

        if not self._pulse_applied and t >= self.settle_before:
            apply_wrench(self.world, self.link, self.model, self.torque_y)
            self._pulse_applied = True
            self.get_logger().info(f"Applied {self.torque_y} N*m push")
        elif (self._pulse_applied and not self._pulse_cleared
              and t >= self.settle_before + self.pulse_duration):
            clear_wrench(self.world, self.link, self.model)
            self._pulse_cleared = True
            self.get_logger().info("Cleared push")

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
        n_samples_joint_states = len(self.rec_t)
        n_samples_effort = len(self.rec_tau1)
        verdict = classify_verdict(metrics, passed, n_samples_joint_states, n_samples_effort)

        result = {
            "scenario": self.scenario["name"],
            "controller": self.controller_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "n_samples_joint_states": n_samples_joint_states,
            "n_samples_effort": n_samples_effort,
            "metrics": metrics.to_dict(),
            "acceptance": self.scenario["acceptance"],
            "passed": passed,
            "failures": failures,
            "verdict": verdict,
        }

        write_result_json(self.output_path, result)

        status = "PASS" if passed else "FAIL"
        self.get_logger().info(f"=== {status} (verdict={verdict}) === {self.scenario['name']} -> {self.output_path}")
        self.get_logger().info(json.dumps(metrics.to_dict(), indent=2))
        if failures:
            self.get_logger().warn(f"failures: {failures}")

        # INFRA-001: a run that completed and technically "passed"
        # acceptance but was classified INVALID_INFRA (e.g. zero torque
        # the whole time, which check_acceptance has no way to see as a
        # rule) must not exit 0 -- exit code still drives
        # run_repeated_experiment.sh's legacy pass-counting fallback for
        # any external caller that doesn't read verdict from result.json.
        self._exit_code = 0 if verdict == "PASS_CONTROL" else 1


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
    start_wall = time.time()
    discovery_timeout_s = 30.0
    try:
        while rclpy.ok() and not node._finished:
            rclpy.spin_once(node, timeout_sec=0.05)
            if not node.rec_t and (time.time() - start_wall) > discovery_timeout_s:
                reason = (
                    f"no /joint_states received within {discovery_timeout_s}s of "
                    f"startup -- aborting (infra failure, not a physics result). "
                    f"See CTRL-005: the schedule intentionally does not start "
                    f"until real data arrives, so this is a genuine discovery "
                    f"failure, not a slow scenario."
                )
                node.get_logger().error(reason)
                write_infra_failure_result(output_path, args.scenario, args.controller,
                                            VERDICT_INVALID_INFRA, reason)
                node.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()
                raise SystemExit(6)
    except KeyboardInterrupt:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        raise SystemExit(130)
    except SystemExit:
        raise
    except Exception:
        # INFRA-001: FAIL_HARNESS -- the harness/tooling itself broke
        # (an unhandled exception in our own code), which is a distinct
        # failure mode from both a real control failure and an infra
        # discovery timeout. Must not be silently swallowed into an exit
        # code with no artifact -- write what we know and re-raise so the
        # process still exits non-zero.
        reason = "uncaught exception in run_experiment.py: " + traceback.format_exc()
        node.get_logger().error(reason)
        write_infra_failure_result(output_path, args.scenario, args.controller,
                                    VERDICT_FAIL_HARNESS, reason)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        raise SystemExit(7)

    exit_code = getattr(node, "_exit_code", 1)
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
