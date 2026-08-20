#!/usr/bin/env python3
"""Phase 2 Stage D: LQR controller node.

Full-state feedback (q1,q2,q1d,q2d) toward the upright equilibrium, unlike
the decoupled per-joint PD in controller_node.py -- this one accounts for
the coupling between the two links.

    ros2 run double_pendulum_control lqr_node.py
    ros2 run double_pendulum_control lqr_node.py --ros-args \
        -p q1:=100.0 -p q2:=100.0 -p q1d:=10.0 -p q2d:=10.0 -p r1:=0.05 -p r2:=0.05

Gain design (sympy linearization + CARE solve) runs once at node startup
and takes ~1 minute -- this is a one-time cost, matching the original
project's tuning scripts. Requires double_pendulum_description/
spawn.launch.py already running (so /joint_states and
/effort_controller/commands exist).
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from lqr_controller import design_lqr, lqr_torque

JOINT_ORDER = ["joint1", "joint2"]


class LQRControllerNode(Node):
    def __init__(self):
        super().__init__("lqr_controller_node")

        self.declare_parameter("q1", 50.0)
        self.declare_parameter("q2", 50.0)
        self.declare_parameter("q1d", 5.0)
        self.declare_parameter("q2d", 5.0)
        self.declare_parameter("r1", 0.05)
        self.declare_parameter("r2", 0.05)
        self.declare_parameter("rate_hz", 100.0)

        q_diag = (
            self.get_parameter("q1").value,
            self.get_parameter("q2").value,
            self.get_parameter("q1d").value,
            self.get_parameter("q2d").value,
        )
        r_diag = (self.get_parameter("r1").value, self.get_parameter("r2").value)

        self.get_logger().info("Designing LQR gain (linearizing + solving CARE, ~1 min)...")
        self.gains = design_lqr(q_diag=q_diag, r_diag=r_diag)
        self.get_logger().info(f"LQR ready. K =\n{self.gains.K}")

        self._latest = None  # (q1, q2, q1d, q2d)
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 10)
        self.cmd_pub = self.create_publisher(Float64MultiArray, "/effort_controller/commands", 10)

        rate_hz = self.get_parameter("rate_hz").value
        self.create_timer(1.0 / rate_hz, self._on_timer)

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
        tau1, tau2 = lqr_torque(self.gains, q1, q2, q1d, q2d)
        msg = Float64MultiArray()
        msg.data = [tau1, tau2]
        self.cmd_pub.publish(msg)


def main():
    rclpy.init()
    node = LQRControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
