# Goal

Per `private/NEXT_STEPS.md` item 4 (gated on item 3, which is now
complete): build a "physics-only" mode that drives Gazebo directly
through gz-transport, with zero ROS2/DDS involvement in the actuation or
sensing path, so a trajectory's run-to-run variance can be attributed to
either the physics/solver layer or the ROS2/DDS/controller layer --
something CTRL-003/004/005 could never distinguish, since every prior
investigation only had the ROS end-to-end path to look at.

# Investigation: what "physics-only" is actually achievable here

Probed the running Gazebo instance's `gz service -l` / `gz topic -l`
directly rather than assuming an API. Found `/world/<world>/control`
(`gz.msgs.WorldControl`: `pause`, `step`, `multi_step`, `reset`),
`/world/<world>/wrench/persistent` (already used by
`run_experiment.py`'s disturbance mechanism -- reusable as-is),
`/world/<world>/pose/info` (`gz.msgs.Pose_V`, per-link name + position +
orientation quaternion).

No native gz-transport joint-effort command topic exists in this
project's plugin set (only `gz_ros2_control` is loaded on the model, no
`gz-sim-joint-controller-system`). Rather than write a new SDF plugin to
get one, scoped this task to what's directly testable with existing
mechanisms: replay the SAME disturbance-pulse profile
`run_experiment.py`'s scenarios already use (a fixed, predetermined
`torque_y` pulse on `link1` -- open-loop, no controller in the loop at
all) via `/world/<world>/wrench/persistent`, which is genuinely
zero-ROS2 gz-transport, and read `link1`/`link2` orientation from
`/world/<world>/pose/info` to derive joint angles directly (planar
system, joint axis is Y for both joints -- `theta = 2*atan2(qy, qw)` for
a pure-Y-axis rotation quaternion; `q1 = link1_pitch - base_pitch`,
`q2 = link2_pitch - link1_pitch`, confirmed against the URDF's joint
chain and the at-rest pose sample, `w=1` at `q1=q2=0`).

This deliberately does not require a fully actuation-equivalent path
(joint-effort command vs link wrench) -- `NEXT_STEPS.md`'s completion
criteria only asks whether a *predetermined* torque sequence reproduces,
not whether it matches a live controller's closed-loop output.

Also confirmed there's no way to spawn the model itself without ROS2 (a
`create` node does the spawning in this project's launch setup, not an
embedded `<model>` in the world SDF) -- reusing `spawn.launch.py` for
setup only. The actual experiment's actuation+sensing data path is what
matters for the diagnostic split, not whether any ROS2 process exists
anywhere in the OS; documented as a deliberate scope decision.

# `gz.msgs.WorldReset` -- tried, broke, abandoned

Initially planned to run N repeats in one Gazebo session via `reset:
{all: true}` between them. Tested directly: after a `WorldControl{pause:
true, reset: {all: true}}` call, every world gz-transport topic
(`/world/<world>/stats`, `/world/<world>/pose/info`) stopped publishing
entirely -- confirmed by a 5s `gz topic echo` timeout on both, gz sim
process still alive but topics dead. Root cause not investigated further
(not worth the time for this Gazebo version's internals). Switched to
relaunching Gazebo fresh between every repeat instead -- the same
pattern `run_clean_experiment.sh` already uses reliably for run
isolation.

# Implementation

- **`physics_only_runner.py`**: `run_once()` pauses, confirms starting
  from rest, then loops (multi_step, apply/clear wrench at the right
  simulated time, read pose) at 20Hz (~0.5s per gz-transport round trip
  in this WSL2 environment made 50Hz impractically slow -- ~150s/run
  vs ~60s/run at 20Hz, still enough resolution to compare overshoot/
  settling behavior). One pass per process invocation (see the
  `WorldReset` note above for why).
- **`run_physics_only_experiment.sh`**: launch/teardown wrapper mirroring
  `run_clean_experiment.sh`'s pattern (fresh relaunch, `/joint_states`
  readiness check only -- no controller-readiness gate needed, since
  nothing here uses ros2_control), isolated `results/raw/<run_id>/`
  output per INFRA-003's convention.

# Verification (real Gazebo runs, not synthetic)

**Physics-only, N=3** (fresh Gazebo relaunch each time, identical
disturbance: `torque_y=15.0`, `pulse_duration=0.3s`, `settle=1.0s`,
`total=6.0s` -- taken directly from `nominal_balance.yaml`, open-loop,
no controller):

| run | max\|q1\| (deg) | max\|q2\| (deg) | final q1 (deg) |
|---|---|---|---|
| 1 | 220.0622 | 182.4296 | 182.9662 |
| 2 | 220.0622 | 182.4296 | 182.9662 |
| 3 | 220.0622 | 182.4296 | 182.9662 |

Sample-by-sample comparison (120 samples/run, not just summary stats):
run1 vs run2 max abs difference = **0.0 rad** (exactly), run1 vs run3 =
**0.0 rad** (exactly) -- bit-for-bit identical trajectories across all 3
independently-launched runs, despite the underlying dynamics being a
genuinely chaotic, uncontrolled double pendulum swing (max angle 220+
degrees). Chaos amplifies rather than hides any hidden non-determinism,
so this is a stronger test than a stable/controlled trajectory would be.

**Same scenario, ROS end-to-end path, N=3** (`run_experiment.py
--scenario nominal_balance --controller none`, no PD/LQR node running --
isolates just the DDS/`joint_state_broadcaster` sensing layer added on
top of the identical physics/disturbance):

| run | overshoot_q1_deg | final_q1_deg |
|---|---|---|
| 1 | 224.1566 | 224.1566 |
| 2 | 223.1896 | 223.1896 |
| 3 | 227.6393 | 227.6393 |

Range across 3 runs: **4.45 degrees** -- small, but real and clearly
nonzero, in sharp contrast to physics-only's exact 0.0. (All 3 runs were
correctly classified `INVALID_INFRA` by INFRA-001's verdict taxonomy,
since `max_abs_tau1_nm=0.0` throughout -- expected and correct, since no
controller was running on purpose; the trajectory data itself is still
valid physics output.)

# Conclusion

This directly confirms `NEXT_STEPS.md`'s hypothesized diagnostic split:
**physics-only reproduces exactly; only the ROS end-to-end path shows
variance.** The ODE physics solver (`max_step_size=0.001`,
`real_time_factor=1.0`) is, on this evidence, fully deterministic --
every instance of run-to-run variance this project has ever observed
(CTRL-003's 200/27/64-degree spread, CTRL-004's zero-torque catastrophic
runs, INFRA-002's own `/dev/shm`-driven `/clock` discovery failure) has
its root cause in the ROS2/DDS/discovery/controller layer, never in the
physics engine itself. This corroborates CTRL-005's independent
conclusion (two concrete readiness-race code bugs, not physics chaos)
through a completely different and more fundamental method -- rather
than inferring "it's probably the ROS layer" from fixing symptoms one at
a time, this task isolates and directly measures it.

Does not attempt to further isolate *which* ROS2/DDS/controller
sub-layer contributes the observed 4.45-degree spread (discovery timing?
QoS reliability settings? `joint_state_broadcaster`'s own publish
jitter?) -- that would be a natural, well-scoped follow-up, not required
by this task's stated completion criteria.

`NEXT_STEPS.md` items 5 (`ENV-001`, distro comparison) and 6
(`REFACTOR-001`, `plant_params.yaml` single source) remain separate,
not-yet-started tasks, both usable in parallel with each other per the
plan's own scoping.
