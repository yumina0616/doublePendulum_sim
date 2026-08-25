#!/usr/bin/env python3
"""Phase 2 Stage B: PD controller node.

Reads /joint_states, drives the double pendulum toward the upright
equilibrium (q1=q2=0) with an independent per-joint PD law, and publishes
torque commands to /effort_controller/commands (order = [joint1, joint2]).

    ros2 run double_pendulum_control controller_node.py
    ros2 run double_pendulum_control controller_node.py --ros-args \
        -p kp1:=80.0 -p kd1:=15.0 -p kp2:=20.0 -p kd2:=3.0

Requires double_pendulum_description/spawn.launch.py already running (so
/joint_states and /effort_controller/commands exist).
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from pd_controller import PDGains, pd_torque

JOINT_ORDER = ["joint1", "joint2"]


class PDControllerNode(Node):
    def __init__(self):
        super().__init__("pd_controller_node")

        self.declare_parameter("kp1", 80.0)
        self.declare_parameter("kd1", 15.0)
        self.declare_parameter("kp2", 20.0)
        self.declare_parameter("kd2", 3.0)
        self.declare_parameter("rate_hz", 100.0)

        self.gains = PDGains(
            kp1=self.get_parameter("kp1").value,
            kd1=self.get_parameter("kd1").value,
            kp2=self.get_parameter("kp2").value,
            kd2=self.get_parameter("kd2").value,
        )

        self._latest = None  # (q1, q2, q1d, q2d)
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 10)
        self.cmd_pub = self.create_publisher(Float64MultiArray, "/effort_controller/commands", 10)

        rate_hz = self.get_parameter("rate_hz").value
        self.create_timer(1.0 / rate_hz, self._on_timer)

        self.get_logger().info(
            f"PD controller started: kp1={self.gains.kp1} kd1={self.gains.kd1} "
            f"kp2={self.gains.kp2} kd2={self.gains.kd2}"
        )

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
        tau1, tau2 = pd_torque(self.gains, q1, q2, q1d, q2d)
        msg = Float64MultiArray()
        msg.data = [tau1, tau2]
        self.cmd_pub.publish(msg)


def main():
    rclpy.init()
    node = PDControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
