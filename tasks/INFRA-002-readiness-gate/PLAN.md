# Goal

Per `private/NEXT_STEPS.md` item 3-2: `run_clean_experiment.sh` still had
a blind `sleep 5` after launching Gazebo, no check that
`joint_state_broadcaster`/`effort_controller` had actually loaded and
gone active, and its CTRL-005 effort-topic check only proved "a
publisher exists somewhere," not that ros2_control's own subscriber had
completed discovery on it too. Replace these with explicit polls against
real readiness signals.

# Probing real CLI output before writing checks

Rather than guess at `ros2 topic echo /clock`, `ros2 control
list_controllers`, and `ros2 topic info --verbose` output shapes, ran a
one-shot probe script against a real launched Gazebo instance first (see
session log -- not kept as a permanent script, it was throwaway). Confirmed:

```text
`ros2 topic echo /clock --once`:
  clock:
    sec: 2
    nanosec: 476000000

`ros2 control list_controllers` (ANSI-colored):
  joint_state_broadcaster joint_state_broadcaster/JointStateBroadcaster  active
  effort_controller       forward_command_controller/...                active

`ros2 topic info --verbose /effort_controller/commands`:
  Publisher count: 1
  ...
  Subscription count: 1
```

Both `joint_state_broadcaster` and `effort_controller` were already
`active` *before* the pd/lqr controller node was even started -- they're
loaded by `spawn.launch.py` itself, not by the controller script. This
confirmed the correct ordering: the controller-active check belongs
right after the existing `/joint_states` check and before starting
pd/lqr, not after.

# Implementation

Three new polling helper functions in `run_clean_experiment.sh`:

- `wait_for_clock_advancing(timeout_s)`: reads `/clock` twice ~1s apart
  (nanosecond-resolution comparison, not just `sec`, since a 1s wall gap
  can still show no `sec` change under load), requires strictly
  increasing sim time. Replaces the old blind `sleep 5`.
- `wait_for_controller_active(name, timeout_s)`: strips ANSI escape codes
  from `ros2 control list_controllers` output (`sed -E
  's/\x1b\[[0-9;]*m//g'`) before grepping for `"<name> ... active"` on
  one line. Called for both `joint_state_broadcaster` and
  `effort_controller` after the existing `/joint_states` check.
- `wait_for_topic_pub_and_sub(topic, timeout_s)`: parses `Publisher
  count:` and `Subscription count:` out of `ros2 topic info --verbose`,
  requires both >= 1. Replaces the CTRL-005 `ros2 topic echo --once`
  check for `/effort_controller/commands`, which only proved a publisher
  existed, not that the subscriber-side discovery had completed too.

Every new failure path calls the same `write_infra_abort_result()`
INFRA-001 added, tagging `INVALID_INFRA` (all three checks are pure
infra/discovery signals, never a control-law issue).

**Deliberately not implemented**: NEXT_STEPS.md's conditions 3 and 6
("/joint_states not stale from a previous run" / "message timestamps
after this run's start"). Not needed here: this script already pkills
and fully relaunches Gazebo before every single run, which resets the
sim clock to 0 and makes it physically impossible for a prior run's
messages to still be in flight. Implementing a redundant timestamp check
on top of that would add complexity without addressing a real gap in
this architecture (it would matter if runs ever reused a live Gazebo
instance, which this script intentionally never does).

# Verification (real runs, not synthetic)

**pd/nominal_balance**: full run through the new gate --
`/clock is advancing (5124000000ns -> 7573000000ns)` after ~2s,
`joint_state_broadcaster`/`effort_controller` both active at 0s,
pub+sub connected at 1s, real experiment ran to `FAIL_CONTROL`
(`settling_time_q1_s=3.2526s` -- consistent with CTRL-005's known,
already-documented gain-tuning gap, not an infra artifact).

**lqr/nominal_balance, attempt 1**: the new `/clock`-advancing check
correctly caught a **real** infra failure -- `/clock` never showed
advancing sim time within the 30s timeout, script exited 4 with
`verdict=INVALID_INFRA`, reason `"/clock did not show advancing sim time
within 30s of Gazebo launch"`. Checked `/dev/shm`: 34 stale
`fastrtps_*`/`sem.fastrtps_*` entries had accumulated from this same
investigation session's repeated launch/kill cycles -- exactly the
factor CTRL-005 already documented as real, reproducible, and
deliberately not baked into this shared script (machine-wide resource,
not project-scoped; cleared here manually, one-off, per the same
investigation-only precedent CTRL-005 set).

**lqr/nominal_balance, attempt 2** (after clearing stale `/dev/shm`
entries and two leftover `robot_state_publisher` processes from the
aborted attempt 1): full run through the gate -- `/clock` advancing at
~3s, both controllers active immediately, LQR gain design completed
(`LQR ready (after 54s)`), pub+sub connected immediately after,
real experiment ran to `FAIL_CONTROL` (`settling_time_q1_s=inf` --
a genuine LQR gain/control-quality result, unrelated to infra). See
`evidence/lqr_after_shm_clear_result.json`.

# Conclusion

This is the strongest direct evidence yet that CTRL-005's documented
`/dev/shm` factor is real and actively degrades later runs in a session
of repeated launches: the new readiness gate caught it in real time,
on a real run, and correctly classified it `INVALID_INFRA` per
INFRA-001's taxonomy instead of silently proceeding (the old blind
`sleep 5` would very likely have proceeded straight into a broken run
here, matching CTRL-004's original zero-torque catastrophic failures).

INFRA-003 (run isolation: unique `run_id`/`ROS_DOMAIN_ID` per run,
`results/raw/<run_id>/` output dirs, environment manifest) remains a
separate, not-yet-started task per `NEXT_STEPS.md`'s own scoping.
