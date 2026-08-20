#!/usr/bin/env python3
"""Reproducible disturbance / initial-condition test pulse.

Scripted version of the manual two-command torque nudge used during Phase
1/2 sanity checks (`ros2 topic pub ... {data: [10.0, 0.0]}` then `{data:
[0.0, 0.0]}`). Publishes a torque pulse to /effort_controller/commands for
a fixed duration, then releases it back to zero.

IMPORTANT caveat (found 2026-08-20): if a controller node (controller_node.py
/ lqr_node.py) is also running, it publishes to this *same* topic at 100Hz
and will overwrite a single one-shot pulse within one control cycle -- the
pulse becomes invisible. To reliably win the race against the controller's
continuous publishing, this script now re-publishes the pulse value in a
tight loop (default 500Hz) for the whole duration instead of a single
publish. This is a workaround, not the physically correct way to inject an
external disturbance (that would be an actual force applied to the link via
Gazebo's ApplyLinkWrench system, independent of the ros2_control command
topic) -- a proper wrench-based scenario is deferred to the Phase 3
evaluation harness. See private/roadmap.md.

Run this right after spawn.launch.py (with or without a PD/LQR controller
node also running) to knock the pendulum off the upright equilibrium and
watch it fall (no controller) or recover (controller running).

    ros2 run double_pendulum_eval disturbance.py --tau1 10.0 --duration 0.3
    ros2 run double_pendulum_eval disturbance.py --tau2 -5.0 --duration 0.2
"""
import argparse
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray


class DisturbancePulse(Node):
    def __init__(self, tau1: float, tau2: float, duration: float, rate_hz: float):
        super().__init__("disturbance_pulse")
        self.pub = self.create_publisher(Float64MultiArray, "/effort_controller/commands", 10)
        time.sleep(0.3)  # let the publisher discover the existing subscriber

        msg = Float64MultiArray()
        msg.data = [tau1, tau2]
        self.get_logger().info(
            f"Applying pulse tau1={tau1} tau2={tau2} for {duration}s at {rate_hz}Hz "
            "(fights any active controller for the topic -- see module docstring)"
        )
        period = 1.0 / rate_hz
        n_repeats = max(1, int(duration / period))
        for _ in range(n_repeats):
            self.pub.publish(msg)
            time.sleep(period)

        zero = Float64MultiArray()
        zero.data = [0.0, 0.0]
        self.pub.publish(zero)
        self.get_logger().info("Released (tau=0)")
        time.sleep(0.2)  # let the release message flush before shutdown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau1", type=float, default=0.0, help="joint1 pulse torque [N*m]")
    parser.add_argument("--tau2", type=float, default=0.0, help="joint2 pulse torque [N*m]")
    parser.add_argument("--duration", type=float, default=0.3, help="pulse duration [s]")
    parser.add_argument(
        "--rate_hz", type=float, default=500.0,
        help="re-publish rate during the pulse; must be faster than any active "
             "controller node's publish rate (default 100Hz) to reliably win",
    )
    args, _ = parser.parse_known_args()  # ignore ros2's own --ros-args etc.

    rclpy.init()
    node = DisturbancePulse(args.tau1, args.tau2, args.duration, args.rate_hz)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
