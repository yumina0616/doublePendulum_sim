#!/usr/bin/env python3
"""PHYS-001: physics-only harness.

Injects a predetermined torque sequence and reads back state entirely
through gz-transport (Gazebo's own native pub/sub -- NOT ROS2/DDS):
  - torque injection: /world/<world>/wrench/persistent (same mechanism
    run_experiment.py already uses for the disturbance pulse)
  - stepping: /world/<world>/control (gz.msgs.WorldControl -- pause +
    multi_step, so time only advances when this script says so)
  - state readout: /world/<world>/pose/info (gz.msgs.Pose_V) -- link
    orientation quaternions, converted to joint angles directly, never
    touching /joint_states or any ROS2 topic

Assumes Gazebo is already running with the double_pendulum model spawned
(e.g. via `ros2 launch double_pendulum_description spawn.launch.py
headless:=true`) -- ROS2/ros2_control may be active in the background
(joint_state_broadcaster, effort_controller, controller_manager), but
this script never sends or reads anything through them. That's the
actual isolation this task needs: not "no ROS2 process anywhere in the
OS" (which would need a hand-built plugin-free world SDF), but "this
experiment's own actuation+sensing data path never touches ROS2/DDS".

Replays the SAME disturbance-pulse profile run_experiment.py's
nominal_balance/impulse scenarios already use (settle, then a fixed
torque_y pulse on link1, then clear) -- deliberately open-loop (no
controller in the loop at all), so this only tests solver+timestep
reproducibility, not control-law reproducibility.

Usage:
    physics_only_runner.py --output /tmp/phys_only_result.json
"""
import argparse
import json
import math
import re
import subprocess
import time

WORLD = "double_pendulum_world"
MODEL = "double_pendulum"

SETTLE_BEFORE_S = 1.0
TORQUE_Y = 15.0
PULSE_DURATION_S = 0.3
TOTAL_DURATION_S = 6.0
DT_S = 0.001  # must match empty_world.sdf's max_step_size
SAMPLE_EVERY_S = 0.05  # ~20Hz -- each gz service/topic round trip is ~0.5s in
# this WSL2 environment, so 50Hz (run_experiment.py's ROS-side rate) would
# make one run take minutes; 20Hz keeps ~120 samples over 6s (still enough
# resolution to compare max overshoot/settling behavior) at ~60s/run.

POSE_BLOCK_RE_TEMPLATE = r'name: "{name}".*?orientation \{{([^}}]*)\}}'


def gz_control(pause=None, multi_step=None, timeout_s=5):
    parts = []
    if pause is not None:
        parts.append(f"pause: {'true' if pause else 'false'}")
    if multi_step is not None:
        parts.append(f"multi_step: {multi_step}")
    req = ", ".join(parts)
    cmd = ["gz", "service", "-s", f"/world/{WORLD}/control",
           "--reqtype", "gz.msgs.WorldControl", "--reptype", "gz.msgs.Boolean",
           "--timeout", str(int(timeout_s * 1000)), "--req", req]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 3)
    if "true" not in r.stdout:
        raise RuntimeError(f"gz world control call failed: req={req!r} stdout={r.stdout!r} stderr={r.stderr!r}")


def apply_wrench(link, torque_y):
    entity_name = f"{MODEL}::{link}"
    req = (f'entity: {{name: "{entity_name}", type: LINK}}, '
           f"wrench: {{torque: {{y: {torque_y}}}}}")
    subprocess.run(["gz", "topic", "-t", f"/world/{WORLD}/wrench/persistent",
                    "-m", "gz.msgs.EntityWrench", "-p", req], check=True, capture_output=True)


def clear_wrench(link):
    entity_name = f"{MODEL}::{link}"
    req = f'name: "{entity_name}", type: LINK'
    subprocess.run(["gz", "topic", "-t", f"/world/{WORLD}/wrench/clear",
                    "-m", "gz.msgs.Entity", "-p", req], check=True, capture_output=True)


def read_pose_text(timeout_s=5):
    r = subprocess.run(
        ["gz", "topic", "-e", "-t", f"/world/{WORLD}/pose/info", "-n", "1"],
        capture_output=True, text=True, timeout=timeout_s)
    return r.stdout


def parse_pitch(pose_text, link_name):
    pattern = re.compile(POSE_BLOCK_RE_TEMPLATE.format(name=re.escape(link_name)), re.DOTALL)
    m = pattern.search(pose_text)
    if not m:
        return None
    block = m.group(1)
    w = 1.0
    y = 0.0
    wm = re.search(r'w:\s*([-\d.eE]+)', block)
    ym = re.search(r'y:\s*([-\d.eE]+)', block)
    if wm:
        w = float(wm.group(1))
    if ym:
        y = float(ym.group(1))
    return 2.0 * math.atan2(y, w)


def read_joint_angles():
    pose_text = read_pose_text()
    base_pitch = parse_pitch(pose_text, "base_link")
    link1_pitch = parse_pitch(pose_text, "link1")
    link2_pitch = parse_pitch(pose_text, "link2")
    if base_pitch is None or link1_pitch is None or link2_pitch is None:
        raise RuntimeError(f"could not parse all link poses from:\n{pose_text[:2000]}")
    q1 = link1_pitch - base_pitch
    q2 = link2_pitch - link1_pitch
    return q1, q2


def run_once():
    gz_control(pause=True)
    # confirm we're starting from rest -- a stale prior run's residual
    # motion would silently corrupt reproducibility comparisons
    q1_0, q2_0 = read_joint_angles()

    steps_per_sample = max(1, round(SAMPLE_EVERY_S / DT_S))
    n_samples = round(TOTAL_DURATION_S / SAMPLE_EVERY_S)

    rec_t, rec_q1, rec_q2 = [], [], []
    pulse_applied = False
    pulse_cleared = False
    t = 0.0
    for i in range(n_samples):
        if not pulse_applied and t >= SETTLE_BEFORE_S:
            apply_wrench("link1", TORQUE_Y)
            pulse_applied = True
        elif pulse_applied and not pulse_cleared and t >= SETTLE_BEFORE_S + PULSE_DURATION_S:
            clear_wrench("link1")
            pulse_cleared = True

        gz_control(pause=True, multi_step=steps_per_sample)
        t += steps_per_sample * DT_S
        q1, q2 = read_joint_angles()
        rec_t.append(round(t, 6))
        rec_q1.append(q1)
        rec_q2.append(q2)
        if (i + 1) % 20 == 0:
            print(f"  ...{i + 1}/{n_samples} samples (t={t:.2f}s)", flush=True)

    return {
        "initial_q1": q1_0,
        "initial_q2": q2_0,
        "t": rec_t,
        "q1": rec_q1,
        "q2": rec_q2,
        "max_abs_q1_deg": math.degrees(max(abs(v) for v in rec_q1)),
        "max_abs_q2_deg": math.degrees(max(abs(v) for v in rec_q2)),
        "final_q1_deg": math.degrees(rec_q1[-1]),
        "final_q2_deg": math.degrees(rec_q2[-1]),
    }


def main():
    # NOTE: does exactly one pass per invocation, against a freshly
    # launched Gazebo instance -- gz.msgs.WorldReset (reset: {all: true})
    # was tried for in-process repeats and found to break this Gazebo
    # version's (8.14) topic publishing entirely (stats/pose/info both
    # stopped publishing after a reset call while paused, confirmed by
    # direct testing). Repeats are handled by the wrapper shell script
    # instead, relaunching Gazebo fresh each time -- the same pattern
    # run_clean_experiment.sh already uses reliably for run isolation.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    start = time.time()
    result = run_once()
    result["wall_time_s"] = round(time.time() - start, 2)
    print(f"max_abs_q1_deg={result['max_abs_q1_deg']:.4f} "
          f"max_abs_q2_deg={result['max_abs_q2_deg']:.4f} "
          f"final_q1_deg={result['final_q1_deg']:.4f} "
          f"wall_time={result['wall_time_s']}s")

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
