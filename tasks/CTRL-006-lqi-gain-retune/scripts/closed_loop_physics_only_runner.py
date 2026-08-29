#!/usr/bin/env python3
"""PHYS-002: closed-loop physics-only harness.

Runs the LQI controller in a direct Python loop against Gazebo's physics
engine only -- no ROS2/DDS anywhere in the actuation/sensing path -- to
answer the question DIAG-001 deferred: is LQI's slow real-Gazebo settling
(3.3-3.4s, see private/roadmap.md) caused by ROS2 timing jitter, or by
the model/controller itself?

Per LQI_ROOT_CAUSE_PLAN.md's explicit instructions, the control law is
NOT reimplemented here -- it reuses lqr_node.py's exact load_cached_gains
(same stale-gain check) and lqr_controller.py's exact lqr_torque, and
duplicates lqr_node.py's integrator/anti-windup update order line-for-line
(qi update BEFORE computing tau, using the fixed nominal dt -- see
_on_timer in lqr_node.py). If this experiment's logic ever diverges from
the live node's, the comparison it produces is meaningless.

Actuation and sensing both go through gz-transport, never ROS2:
  - torque: /model/<model>/joint/joint{1,2}/cmd_force (gz.msgs.Double),
    consumed by the gz-sim-apply-joint-force-system plugin added to
    double_pendulum.urdf.xacro for this task (PHYS-002) -- unlike
    ApplyLinkWrench (used only for the disturbance pulse below), this
    applies a true joint actuation torque with correct reaction pairs.
    NOTE: that plugin's <gazebo> block must be declared AFTER the
    gz_ros2_control block in the xacro -- gz-sim's per-tick JointForceCmd
    write is last-writer-wins, and gz_ros2_control's hardware interface
    writes its own (zero, since no ROS controller runs during this
    experiment) commanded effort every step. Declared before it, this
    plugin's torque was silently overwritten every tick (confirmed by
    direct testing: 20 N*m for 0.5s produced exactly 0.0000 deg motion
    until reordered).
  - disturbance pulse: EntityWrench on the link (apply_wrench/clear_wrench,
    reused verbatim from physics_only_runner.py -- same mechanism
    wrench_disturbance.py/PHYS-001 already use), separate from actuation.
  - stepping: /world/<world>/control (gz.msgs.WorldControl, pause +
    multi_step) via gz-transport Python bindings (gz.transport13) --
    confirmed fast and reliable (~4ms/call).
  - state read: /world/<world>/pose/info via the CLI (`gz topic -e -n 1`,
    reused as physics_only_runner.read_joint_angles) -- gz-transport
    Python bindings' subscribe() was found to never actually deliver
    messages in this WSL2 environment (discovery succeeds, data channel
    doesn't -- confirmed on /clock too, unrelated to this model), so this
    one piece still shells out. A pure request/reply ECS state query
    (/world/<world>/state, gz.msgs.Empty -> SerializedStepMap) exists and
    avoids the subprocess, but its components are keyed by opaque
    numeric type-ids with no public string-name mapping available from
    Python -- not worth the fragility for one call/tick.
  - velocity (q1d, q2d): NOT read directly (no gz-native joint-velocity
    topic is loaded in this world -- only gz_ros2_control's ROS-side
    state interface has real velocity, and touching that would defeat
    the whole point). Estimated via backward finite difference of
    position over the exact, jitter-free 10ms control step
    ((q - q_prev) / dt). This differs from the real node (which reads
    ros2_control's true instantaneous velocity) by an O(dt) bias/lag --
    documented as a limitation, not fixed, since dt here is exact by
    construction (no jitter) unlike the real ROS2 path this is being
    compared against.

Per-tick cost: with step+torque-publish via gz-transport Python bindings
(gz.transport13, request/reply + advertise/publish -- both confirmed
working) and only the pose read via CLI subprocess, ~150ms/tick under the
full spawn.launch.py + controller_manager stack (measured directly) --
about 90s for a full 601-sample/6s-sim-time run. An earlier all-CLI-
subprocess design measured ~2.2s/tick (~22min/run) purely from repeated
`gz` process spawn overhead under this stack's CPU load; switching step
and publish to the Python bindings cut that ~15x with no change in what
is actually being tested.

Assumes Gazebo is already running with the model spawned via
`ros2 launch double_pendulum_description spawn.launch.py headless:=true`
(robot_state_publisher must be part of that -- gz_ros2_control's plugin
polls for it in a tight loop otherwise; harmless, but confirmed
independently to NOT be what breaks pose/info -- that was purely the
xacro plugin-ordering bug above). ROS2/ros2_control is present in the
background exactly as in PHYS-001 (no controller node publishing to
/effort_controller/commands, so its own effort command stays zero) but
this script's own data path never touches it.

Usage:
    closed_loop_physics_only_runner.py --scenario nominal_balance --output /tmp/phys002_result.json
"""
import argparse
import json
import math
import os
import sys
import time

_EVAL_SCRIPTS = os.path.expanduser("~/agentic_double_pendulum/src/double_pendulum_eval/scripts")
_EVAL_DIR = os.path.expanduser("~/agentic_double_pendulum/src/double_pendulum_eval")
_CONTROL_INSTALL = os.path.expanduser(
    "~/agentic_double_pendulum/install/double_pendulum_control/lib/double_pendulum_control"
)
sys.path.insert(0, _CONTROL_INSTALL)
sys.path.insert(0, _EVAL_SCRIPTS)
sys.path.insert(0, _EVAL_DIR)

# Import order matters: lqr_node/lqr_controller must be imported BEFORE
# autotune_lqr, because autotune_lqr.py's own module-level sys.path.insert
# points at src/double_pendulum_control (no gain cache there -- only
# install/ has lqr_gain_cache.json) and would shadow _CONTROL_INSTALL
# above for these two names if imported first. Once imported, Python
# caches them in sys.modules, so autotune_lqr's later
# `from lqr_controller import ...` reuses the already-correct module
# instead of re-resolving via sys.path.
from lqr_node import load_cached_gains  # noqa: E402
from lqr_controller import lqr_torque  # noqa: E402
from physics_only_runner import gz_control, apply_wrench, clear_wrench, read_joint_angles, WORLD, MODEL  # noqa: E402
from autotune_lqr import load_scenario  # noqa: E402
from metrics import compute_metrics, check_acceptance, classify_verdict  # noqa: E402

import gz.transport13 as transport  # noqa: E402
from gz.msgs10.double_pb2 import Double  # noqa: E402

# Must match lqr_node.py's declare_parameter defaults exactly -- same
# convention design_lqr_gains.py's own CLI defaults already follow
# (independently hardcoded there too; there is no single shared source
# for these outside the ROS parameter declarations themselves).
Q_DIAG = (187.0706, 174.4019, 50.4355, 3.2031, 0.0059, 11.0445)  # CTRL-006 re-tuned
R_DIAG = (0.0106, 0.0822)  # CTRL-006 re-tuned
QI_MAX = 3.0
RATE_HZ = 100.0
CONTROL_DT_S = 1.0 / RATE_HZ


def apply_joint_torque(pub, torque):
    msg = Double()
    msg.data = torque
    pub.publish(msg)


def step_physics(node, n):
    from gz.msgs10.world_control_pb2 import WorldControl
    from gz.msgs10.boolean_pb2 import Boolean
    req = WorldControl()
    req.pause = True
    req.multi_step = n
    ok, result = node.request(f"/world/{WORLD}/control", req, WorldControl, Boolean, 5000)
    if not (ok and result.data):
        raise RuntimeError(f"world control step failed (ok={ok})")


def run_once(scenario: dict):
    gains = load_cached_gains(Q_DIAG, R_DIAG)

    d = scenario["disturbance"]
    link = d.get("link", "link1")
    torque_y = float(d.get("torque_y", 0.0))
    pulse_duration = float(d.get("pulse_duration", 0.3))
    settle_before = float(scenario["settle_time_before_s"])
    total_duration = float(scenario["total_duration_s"])

    steps_per_control = round(CONTROL_DT_S / 0.001)  # world's max_step_size
    n_samples = round(total_duration / CONTROL_DT_S) + 1

    node = transport.Node()
    pub1 = node.advertise(f"/model/{MODEL}/joint/joint1/cmd_force", Double)
    pub2 = node.advertise(f"/model/{MODEL}/joint/joint2/cmd_force", Double)
    time.sleep(1.0)  # let discovery settle before the first publish

    gz_control(pause=True)  # PHYS-001 precedent: confirm starting from rest
    q1, q2 = read_joint_angles()
    q1_0, q2_0 = q1, q2
    q1_prev, q2_prev = q1, q2
    qi1 = qi2 = 0.0
    pulse_applied = pulse_cleared = False

    rec_t, rec_q1, rec_q2, rec_tau1, rec_tau2 = [], [], [], [], []

    start = time.time()
    for i in range(n_samples):
        t = i * CONTROL_DT_S

        if i == 0:
            q1d, q2d = 0.0, 0.0
        else:
            q1d = (q1 - q1_prev) / CONTROL_DT_S
            q2d = (q2 - q2_prev) / CONTROL_DT_S

        # integrator update BEFORE computing tau, using this sample's q --
        # matches lqr_node.py's _on_timer exactly.
        qi1 = max(-QI_MAX, min(QI_MAX, qi1 + q1 * CONTROL_DT_S))
        qi2 = max(-QI_MAX, min(QI_MAX, qi2 + q2 * CONTROL_DT_S))

        tau1, tau2 = lqr_torque(gains, q1, q2, q1d, q2d, qi1, qi2)

        rec_t.append(round(t, 6))
        rec_q1.append(q1)
        rec_q2.append(q2)
        rec_tau1.append(tau1)
        rec_tau2.append(tau2)

        apply_joint_torque(pub1, tau1)
        apply_joint_torque(pub2, tau2)

        if not pulse_applied and t >= settle_before:
            apply_wrench(link, torque_y)
            pulse_applied = True
        elif pulse_applied and not pulse_cleared and t >= settle_before + pulse_duration:
            clear_wrench(link)
            pulse_cleared = True

        if i < n_samples - 1:
            step_physics(node, steps_per_control)
            q1_prev, q2_prev = q1, q2
            q1, q2 = read_joint_angles()

        if (i + 1) % 100 == 0:
            print(f"  ...{i + 1}/{n_samples} samples (t={t:.2f}s)", flush=True)

    wall_time_s = round(time.time() - start, 2)

    event_t = settle_before
    band_deg = float(scenario.get("settle_band_deg", 1.0))
    metrics = compute_metrics(rec_t, rec_q1, rec_q2, rec_tau1, rec_tau2, event_t, settle_band_deg=band_deg)
    passed, failures = check_acceptance(metrics, scenario["acceptance"])
    verdict = classify_verdict(metrics, passed, len(rec_t), len(rec_tau1))

    return {
        "scenario": scenario["name"],
        "controller": "lqr_closed_loop_physics_only",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "initial_q1_deg": math.degrees(q1_0),
        "initial_q2_deg": math.degrees(q2_0),
        "n_samples_joint_states": len(rec_t),
        "n_samples_effort": len(rec_tau1),
        "metrics": metrics.to_dict(),
        "acceptance": scenario["acceptance"],
        "passed": passed,
        "failures": failures,
        "verdict": verdict,
        "wall_time_s": wall_time_s,
        "t": rec_t,
        "q1": rec_q1,
        "q2": rec_q2,
        "tau1": rec_tau1,
        "tau2": rec_tau2,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="nominal_balance")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    print(f"Scenario: {scenario['name']} (closed-loop physics-only, gz-transport only, no ROS2/DDS)")

    result = run_once(scenario)

    status = "PASS" if result["passed"] else "FAIL"
    print(f"=== {status} (verdict={result['verdict']}) === wall_time={result['wall_time_s']}s")
    print(json.dumps(result["metrics"], indent=2))
    if result["failures"]:
        print("failures:", result["failures"])

    tmp = args.output + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=2)
    os.replace(tmp, args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
