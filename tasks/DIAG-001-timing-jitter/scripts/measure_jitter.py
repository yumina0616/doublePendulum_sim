#!/usr/bin/env python3
"""DIAG-001: records real arrival timestamps for /joint_states and
/effort_controller/commands during a live run, to measure whether
ROS2/DDS timing jitter around the two nominal periods this project's
LQI loop assumes (controller_manager's 200Hz update_rate -> 5ms for
/joint_states; lqr_node.py's own 100Hz control timer -> 10ms for
/effort_controller/commands) is actually present, and how large it is.

Records wall-clock (time.monotonic()) arrival time for every message on
both topics -- this is "when did this process actually get the data",
which is what matters for a control loop, as opposed to simulated time.
Also records each JointState message's header.stamp (sim time) purely
for reference (comparing sim-time spacing vs wall-clock spacing is
itself informative: physics-only mode has zero wall-clock jitter by
construction, so a real spacing mismatch here is squarely a ROS2/DDS-side
phenomenon).

Float64MultiArray (the command message type) carries no header/stamp,
so only wall-clock receipt time is available for it -- noted, not worked
around, since this script must not invent data that isn't really there.

Usage:
    measure_jitter.py --duration 9.0 --out /path/to/raw_timestamps.json

Run this concurrently with (started right as) a live experiment window,
e.g. via run_diag001.sh, which launches it against a real
run_clean_experiment.sh lqr nominal_balance invocation.
"""
import argparse
import json
import os
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray


class JitterRecorder(Node):
    def __init__(self, duration_s: float):
        super().__init__("jitter_recorder")
        self.joint_states_wall = []
        self.joint_states_sim_stamp = []
        self.commands_wall = []
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 100)
        self.create_subscription(Float64MultiArray, "/effort_controller/commands", self._on_commands, 100)
        self._deadline = time.monotonic() + duration_s

    def _on_joint_states(self, msg: JointState):
        self.joint_states_wall.append(time.monotonic())
        stamp = msg.header.stamp
        self.joint_states_sim_stamp.append(stamp.sec + stamp.nanosec * 1e-9)

    def _on_commands(self, msg: Float64MultiArray):
        self.commands_wall.append(time.monotonic())

    def done(self) -> bool:
        return time.monotonic() >= self._deadline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=9.0,
                     help="how long to record, in seconds (should cover the "
                          "full settle_time_before_s + total_duration_s scenario window)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rclpy.init()
    node = JitterRecorder(args.duration)
    try:
        while rclpy.ok() and not node.done():
            rclpy.spin_once(node, timeout_sec=0.05)
    finally:
        raw = {
            "joint_states_wall_s": node.joint_states_wall,
            "joint_states_sim_stamp_s": node.joint_states_sim_stamp,
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
        print(f"wrote {len(node.joint_states_wall)} joint_states samples, "
              f"{len(node.commands_wall)} command samples -> {out_path}")


if __name__ == "__main__":
    main()
