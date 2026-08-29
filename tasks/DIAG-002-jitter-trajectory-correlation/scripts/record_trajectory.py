#!/usr/bin/env python3
"""DIAG-002: records both real arrival timing AND actual joint values
during a live run, so a single recording can be directly compared
against PHYS-002's known physics-only trajectory on the same time axis,
and also cross-referenced against per-sample arrival jitter -- DIAG-001
recorded timing only, never the values, so it could not answer "when
does the real trajectory actually diverge from what jitter-free physics
predicts".

The "t" axis here deliberately matches run_experiment.py's own
_now_s()/self.t0 convention exactly (wall-clock seconds since the FIRST
real /joint_states message, via self.get_clock().now() -- not
time.monotonic(), not header.stamp) -- this is what
metrics.compute_metrics/settling_time actually operates on for every
other result in this project, so this recording's "t" is directly
comparable to those, and to PHYS-002's physics-only "t" (control-tick
count * exact 10ms, equivalent under this world's real_time_factor=1.0).

Also records the same raw wall-clock arrival timestamps DIAG-001 used
(time.monotonic()), so per-sample jitter can be computed on this exact
same recording -- no need to run twice or reconcile two separate
recordings' timelines.

Usage:
    record_trajectory.py --duration 9.0 --out /path/to/raw_trajectory.json
"""
import argparse
import json
import os
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

JOINT_ORDER = ["joint1", "joint2"]


class TrajectoryRecorder(Node):
    def __init__(self, duration_s: float):
        super().__init__("trajectory_recorder")
        self.t0 = None
        self.rec_t = []
        self.rec_q1 = []
        self.rec_q2 = []
        self.joint_states_wall = []
        self.joint_states_sim_stamp = []
        self.rec_tau_t = []
        self.rec_tau1 = []
        self.rec_tau2 = []
        self.commands_wall = []
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 50)
        self.create_subscription(Float64MultiArray, "/effort_controller/commands", self._on_effort, 50)
        self._deadline = time.monotonic() + duration_s

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
        self.joint_states_wall.append(time.monotonic())
        stamp = msg.header.stamp
        self.joint_states_sim_stamp.append(stamp.sec + stamp.nanosec * 1e-9)

    def _on_effort(self, msg: Float64MultiArray):
        if len(msg.data) < 2:
            return
        t = self._now_s()
        self.rec_tau_t.append(t)
        self.rec_tau1.append(msg.data[0])
        self.rec_tau2.append(msg.data[1])
        self.commands_wall.append(time.monotonic())

    def done(self) -> bool:
        return time.monotonic() >= self._deadline


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--duration", type=float, default=9.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rclpy.init()
    node = TrajectoryRecorder(args.duration)
    try:
        while rclpy.ok() and not node.done():
            rclpy.spin_once(node, timeout_sec=0.05)
    finally:
        raw = {
            "t": node.rec_t,
            "q1": node.rec_q1,
            "q2": node.rec_q2,
            "joint_states_wall_s": node.joint_states_wall,
            "joint_states_sim_stamp_s": node.joint_states_sim_stamp,
            "tau_t": node.rec_tau_t,
            "tau1": node.rec_tau1,
            "tau2": node.rec_tau2,
            "commands_wall_s": node.commands_wall,
        }
        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        tmp = out_path + f".tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(raw, f)
        os.replace(tmp, out_path)
        node.destroy_node()
        rclpy.shutdown()
        print(f"wrote {len(node.rec_t)} joint_states samples, "
              f"{len(node.rec_tau1)} command samples -> {out_path}")


if __name__ == "__main__":
    main()
