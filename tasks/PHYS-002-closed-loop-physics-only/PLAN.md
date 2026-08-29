# PHYS-002: Closed-loop physics-only harness

## Goal

`private/LQI_ROOT_CAUSE_PLAN.md` Task B. DIAG-001 (Task A) measured real
ROS2/DDS timing jitter but explicitly deferred judging whether it's
*significant enough* to explain LQI's slow settling. This task removes
ROS2/DDS from the loop entirely (closed-loop physics-only, exact 10ms
control) and compares the result against a freshly-computed offline
prediction and a fresh real ROS2 end-to-end baseline, to separate
"model/controller problem" (Case 1) from "ROS2 problem" (Case 2).

## Unplanned blocker #1: no way to apply pure joint torque without ROS2

The plan assumed `apply_torque_via_gz_transport()` was straightforward.
The only actuation path already reachable via gz-transport
(`ApplyLinkWrench`, used for the disturbance pulse) applies an *external
wrench* to a single link -- it has no reaction pair on the parent link,
so using it for joint2's actuation would silently make link1 not feel
joint2's reaction torque, a real physical difference from the actual
actuator. Confirmed Gazebo Sim 8.14 ships a plugin for exactly this
(`gz-sim-apply-joint-force-system`, applies true joint-DOF torque via
`/model/<model>/joint/<joint>/cmd_force`), verified its topic name by
spawning a temporary modified URDF and checking `gz topic -l`. Asked the
user to choose between adding this plugin (physically correct) or
falling back to `ApplyLinkWrench` with a documented caveat; user chose
the plugin. Added two `<gazebo>` blocks to
`double_pendulum_description/urdf/double_pendulum.urdf.xacro` (joint1,
joint2).

**Sub-blocker:** once added, 20 N*m applied to joint1 for 0.5s of Gazebo
time produced exactly `0.0000 deg` of motion. Root-caused to plugin
*declaration order*: gz-sim's per-tick `JointForceCmd` write is
last-writer-wins, and `gz_ros2_control`'s hardware interface writes its
own commanded effort (zero, since no ROS controller runs during this
experiment) every step. The `ApplyJointForce` blocks were declared
*before* `gz_ros2_control`'s block, so its zero silently overwrote our
torque every tick. Fixed by moving the two blocks to *after*
`gz_ros2_control`'s block. Reverified directly: 30 N*m on joint1 for 6
ticks (60ms) produced `q2_deg=-56.65` (correct coupled dynamics -- torque
on joint1 visibly swings joint2 too).

## Unplanned blocker #2: gz-transport Python bindings' subscribe() never delivers

Tested `gz.transport13.Node.subscribe()` against `/clock` and
`/world/.../pose/info` (and, separately, `/world/.../dynamic_pose/info`)
in this WSL2 environment: discovery succeeds (`subscribed_topics()`
shows the subscription, `topic_info()` shows a registered publisher) but
the callback never fires -- confirmed over several seconds with a live,
freely-running Gazebo, with a permissive `*args` callback (ruling out a
signature-mismatch swallowing an exception), and with `GZ_IP=127.0.0.1`
forced (ruling out a WSL2 NAT/advertised-address issue). `request()`
(services) and `advertise()/publish()` were separately confirmed to work
correctly and fast. A pure request/reply ECS state query
(`/world/<world>/state`, `gz.msgs.Empty` -> `gz.msgs.SerializedStepMap`)
exists and avoids subscribe entirely, but its components are keyed by
opaque numeric type-ids with no string-name mapping exposed to Python --
decoding it reliably would need reverse-engineering gz-sim's internal
type-id scheme, not worth the fragility for one call. Settled on: step
(`WorldControl` request) and torque publish (`Double` advertise/publish)
via the Python bindings (both confirmed working), pose read via the
already-proven CLI (`gz topic -e -n 1`, same mechanism PHYS-001 uses).

**Performance consequence:** an earlier all-CLI-subprocess design (4
subprocess spawns/tick: 2 torque publishes + 1 step + 1 read) measured
**~2.2s/tick** under the full `spawn.launch.py` + `controller_manager`
stack -- ~22min for one 601-sample run, ~2hr for N=5. Purely from `gz`
process spawn overhead, not from gz-transport itself. Moving step+publish
to the Python bindings (1 subprocess/tick instead of 4) cut this to
**~149ms/tick, ~90s/run** -- confirmed by direct timing before committing
to the full N=5 run.

## Method

`closed_loop_physics_only_runner.py`: imports `lqr_node.load_cached_gains`
and `lqr_controller.lqr_torque` directly (no reimplementation), duplicates
`lqr_node.py`'s integrator/anti-windup update order line-for-line (`qi`
update before computing `tau`, using the fixed nominal `dt` -- see
`_on_timer`). 601 samples (0..6.0s inclusive, matching
`autotune_lqr.simulate_closed_loop`'s own convention) at exactly 10ms.
Velocity (`q1d`, `q2d`) is NOT read directly -- no gz-native
joint-velocity topic is loaded in this world -- and is instead estimated
via backward finite difference of position over the exact, jitter-free
10ms step. This differs from the real node (true instantaneous velocity
from `ros2_control`'s state interface) by an O(dt) bias/lag; documented
as a limitation, not fixed, since it doesn't undermine the "zero jitter
by construction" comparison this arm exists to provide.

Three arms, all against `nominal_balance`, all using the actual currently
cached LQI gain (`q_diag=(50,50,5,5,10,10)`, `r_diag=(0.05,0.05)`, the
real `lqr_node.py` ROS-parameter defaults, matching what
`run_clean_experiment.sh lqr nominal_balance` actually runs with no
extra args):

1. **Offline prediction** (`offline_prediction.py`) -- reuses
   `autotune_lqr.simulate_closed_loop` verbatim (nonlinear RK4 plant +
   linear K, same anti-windup clamp) with the real cached `K` and current
   `plant_params.yaml`. Deterministic, one run.
2. **Closed-loop physics-only** (`closed_loop_physics_only_runner.py` via
   `run_phys002.sh`) -- N=5, full Gazebo relaunch each run (same
   isolation convention as PHYS-001/DIAG-001).
3. **ROS2 e2e real** -- N=5 via the existing, unmodified
   `run_repeated_experiment.sh lqr nominal_balance 5 0.6`.

## Results

| arm | settling_time_q1_s | notes |
|---|---|---|
| offline prediction | **3.25s** (deterministic) | fails 3.0s threshold |
| physics-only (N=5) | **3.24s, all 5 runs identical** | fails 3.0s threshold; fully deterministic (matches PHYS-001's established finding that Gazebo's solver is bit-reproducible when driven this way) |
| ROS2 e2e real (N=5) | **Infinity, 4/4 valid runs** (1 run `INVALID_INFRA` -- no `/joint_states` within 60s, excluded, a plain infra hiccup) | never settles within the 6.0s window at all |

Full numbers: `evidence/comparison.json`, `evidence/offline_prediction.json`,
`evidence/physics_only_run_{1..5}.json`, `evidence/ros2_e2e_lqr_batch/`.

## Interpretation -- reported honestly, not forced into a clean case

Note first: `private/roadmap.md`'s existing narrative cited the offline
prediction as **0.63s** (PASS). That number does not reproduce against
the currently-deployed cached gain + current `plant_params.yaml` --
recomputing it directly (not re-citing the old figure) gives **3.25s**
(FAIL). Either the gain or the plant params (or both) changed since that
note was written, without the offline prediction being recomputed and
re-recorded. **This means the original "0.63s vs 3.3s, 5x gap" framing
that motivated DIAG-001/PHYS-002 was itself based on a stale number.**
Worth fixing going forward (see Next below) but not something this task
can retroactively correct -- reported as found.

Given the *current* numbers, the result does not cleanly match any one
of the plan's three suggested cases:

- **Offline and physics-only agree almost exactly** (3.25s vs 3.24s,
  well within RK4-vs-DART-solver discretization noise). This is
  classic **Case 1** evidence: with ROS2/DDS entirely removed and control
  timing exact, the controller *still* misses the 3.0s spec by the same
  margin the offline model predicts. The marginal-fail behavior is a
  property of this Q/R weighting against the real plant, not of ROS2.
- **But real ROS2 e2e is qualitatively worse than both** -- not "3.3s
  instead of 3.24s" (which would still fit Case 1 with some noise), but
  "never settles within the 6s window at all," in 4/4 valid runs. Physics-only
  and offline both predict clean, repeatable settling at 3.24-3.25s;
  nothing in either explains why the real system fails to settle within
  6s. **This is Case 2 behavior stacked on top of a Case-1 baseline** --
  there IS a real, measurable ROS2/DDS-layer degradation, it's just not
  the *entire* story DIAG-001/PHYS-002 set out to explain, because the
  offline baseline it would need to explain was never actually 0.63s to
  begin with.

So: the LQI gain's marginal failure of the 3.0s spec is a model/tuning
issue (Case 1), independent of ROS2. On top of that, ROS2/DDS adds a
further, real degradation that turns "marginally too slow" into "doesn't
settle at all" (Case 2 characteristics -- plausibly connected to
DIAG-001's measured worst-case jitter spikes of 6.8-9.5ms against a 10ms
control period, though this task doesn't isolate *which* ROS2-layer
factor is responsible, only that removing ROS2/DDS entirely removes this
specific failure mode).

## Completion checklist (against specification.yaml's acceptance)

- [x] N=5 closed-loop physics-only runs, Gazebo fully relaunched each time
- [x] one deterministic offline-prediction run via the actual cached K
- [x] N=5 fresh real ROS2 e2e LQR/nominal_balance runs (unmodified `run_repeated_experiment.sh`)
- [x] all three arms in `evidence/comparison.json`, no Case verdict embedded in code
- [x] Case 1/2/3 classification reported honestly here, including that it doesn't cleanly match a single case

## Next

- `private/roadmap.md`'s "0.63s" note is stale against the current gain/plant_params
  and should be corrected (pointer to this task, not a new investigation).
- The real, ROS2-specific degradation (settles cleanly at physics-only fidelity,
  never settles for real) is now an isolated, well-defined open question -- a
  natural follow-up would correlate DIAG-001's per-sample jitter timestamps
  against exactly *when* the real runs diverge from the physics-only trajectory,
  rather than re-litigating whether jitter exists at all (already answered).
- The LQI gain itself marginally fails the 3.0s spec even under ideal conditions
  (Case 1) -- a Q/R re-tune (`autotune_lqr.py`, already built) is a legitimate,
  separate next step, decoupled from the ROS2 investigation.
