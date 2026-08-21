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
        self.declare_parameter("qi1", 10.0)
        self.declare_parameter("qi2", 10.0)
        self.declare_parameter("r1", 0.05)
        self.declare_parameter("r2", 0.05)
        self.declare_parameter("rate_hz", 100.0)
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
