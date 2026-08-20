#!/usr/bin/env python3
"""Reproducible disturbance / initial-condition test pulse.

Scripted version of the manual two-command torque nudge used during Phase
1/2 sanity checks (`ros2 topic pub ... {data: [10.0, 0.0]}` then `{data:
[0.0, 0.0]}`). Publishes a torque pulse to /effort_controller/commands for
a fixed duration, then releases it back to zero.

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
    def __init__(self, tau1: float, tau2: float, duration: float):
        super().__init__("disturbance_pulse")
        self.pub = self.create_publisher(Float64MultiArray, "/effort_controller/commands", 10)
        time.sleep(0.3)  # let the publisher discover the existing subscriber

        msg = Float64MultiArray()
        msg.data = [tau1, tau2]
        self.get_logger().info(f"Applying pulse tau1={tau1} tau2={tau2} for {duration}s")
        self.pub.publish(msg)

        time.sleep(duration)

        msg = Float64MultiArray()
        msg.data = [0.0, 0.0]
        self.pub.publish(msg)
        self.get_logger().info("Released (tau=0)")
        time.sleep(0.2)  # let the release message flush before shutdown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau1", type=float, default=0.0, help="joint1 pulse torque [N*m]")
    parser.add_argument("--tau2", type=float, default=0.0, help="joint2 pulse torque [N*m]")
    parser.add_argument("--duration", type=float, default=0.3, help="pulse duration [s]")
    args, _ = parser.parse_known_args()  # ignore ros2's own --ros-args etc.

    rclpy.init()
    node = DisturbancePulse(args.tau1, args.tau2, args.duration)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
