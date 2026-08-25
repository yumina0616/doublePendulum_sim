#!/usr/bin/env python3
"""Phase 3: physically-correct disturbance -- a real external push applied
directly to a link via Gazebo's ApplyLinkWrench system, independent of the
ros2_control command topic.

This replaces disturbance.py's approach (racing a pulse against the
controller on /effort_controller/commands, which briefly blacks the
controller out completely instead of letting it keep resisting). A real
Gazebo test with disturbance.py showed the controller can't do anything
about that blackout no matter how it's tuned -- the offline autotune model
confirmed the same push applied *additively* (as a real force would be) is
recoverable with good gains, while the topic-override version isn't. This
script makes the real Gazebo test match that more honest model.

Requires the empty_world.sdf's gz-sim-apply-link-wrench-system plugin
(already added) and the double_pendulum model to be spawned as
"double_pendulum" (spawn.launch.py's default -name).

    ros2 run double_pendulum_eval wrench_disturbance.py --torque_y 15.0 --duration 0.3
    ros2 run double_pendulum_eval wrench_disturbance.py --link link2 --torque_y -10.0 --duration 0.2
"""
import argparse
import subprocess
import time


def apply_wrench(world: str, link: str, model: str, torque_y: float):
    """/wrench applies for a single physics step only -- /wrench/persistent
    is what actually keeps a force applied across steps (confirmed via
    `gz topic -i -t .../wrench/persistent`, which expects EntityWrench,
    same as /wrench)."""
    entity_name = f"{model}::{link}"
    req = (
        f'entity: {{name: "{entity_name}", type: LINK}}, '
        f"wrench: {{torque: {{y: {torque_y}}}}}"
    )
    cmd = [
        "gz", "topic", "-t", f"/world/{world}/wrench/persistent",
        "-m", "gz.msgs.EntityWrench", "-p", req,
    ]
    subprocess.run(cmd, check=True)


def clear_wrench(world: str, link: str, model: str):
    """/wrench/clear expects a plain Entity (not EntityWrench)."""
    entity_name = f"{model}::{link}"
    req = f'name: "{entity_name}", type: LINK'
    cmd = [
        "gz", "topic", "-t", f"/world/{world}/wrench/clear",
        "-m", "gz.msgs.Entity", "-p", req,
    ]
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="double_pendulum_world")
    parser.add_argument("--model", default="double_pendulum")
    parser.add_argument("--link", default="link1", help="link1 (base joint) or link2 (elbow)")
    parser.add_argument("--torque_y", type=float, default=15.0, help="torque about the joint axis [N*m]")
    parser.add_argument("--duration", type=float, default=0.3, help="push duration [s]")
    args, _ = parser.parse_known_args()

    print(f"Applying {args.torque_y} N*m to {args.model}::{args.link} for {args.duration}s...")
    apply_wrench(args.world, args.link, args.model, args.torque_y)
    time.sleep(args.duration)

    print("Clearing wrench...")
    clear_wrench(args.world, args.link, args.model)


if __name__ == "__main__":
    main()
