# Goal

Per `private/LQI_ROOT_CAUSE_PLAN.md` Task A: measure whether real
ROS2/DDS timing jitter actually exists around the two nominal periods
this project's LQI control loop depends on, before building `PHYS-002`
(closed-loop physics-only harness). Cheap, measure-first step -- confirm
or refute the jitter hypothesis's basic plausibility without yet trying
to isolate causation for LQI's slow settling.

Two relevant nominal periods, both confirmed directly from source
(not assumed):
- `/joint_states`: controller_manager's `update_rate: 200` (`controllers.yaml`)
  -> 5ms nominal publish period.
- `/effort_controller/commands`: lqr_node.py's own `rate_hz` parameter,
  default 100.0 -> 10ms nominal publish period (a *separate* timer from
  controller_manager's -- the LQI control loop runs on its own ROS timer,
  acting on whatever `/joint_states` sample is most recently cached,
  not synchronized to controller_manager's own tick).

# Blocker found and fixed first: ros2cli daemon dies on graph launch

Before any jitter could be measured, `run_clean_experiment.sh lqr
nominal_balance` failed its own `/clock` readiness check 5/5 consecutive
times in this WSL2 boot session (30s timeout, every attempt, including
with a manually-restarted daemon before each attempt).

Root-caused via direct probing, not guessed:
- `gz topic -e -t /clock -n 1` (gz-transport, bypassing ROS2 entirely)
  showed real, correctly-advancing sim time throughout every failure --
  Gazebo itself was never the problem.
- `ros2 topic echo /clock --once` (the readiness check's actual call)
  failed with `RuntimeError: !rclpy.ok()`, raised from inside
  `ros2cli.node.direct.DirectNode.__getattr__` (confirmed by reading
  that module's source directly) -- meaning the *shared ros2cli daemon's*
  own long-lived internal node had its rclpy context torn down, and
  every subsequent daemon-mediated call fails identically until the
  daemon process is killed and replaced.
- Reproduced this exact failure 5/5 times, each with the daemon
  confirmed freshly restarted and idle-healthy (`ros2 topic list`
  succeeding) immediately beforehand -- so it isn't a stale daemon from
  an earlier command, it dies again every time this project's ROS graph
  (11+ nodes appearing/exiting in a burst: `robot_state_publisher`,
  `parameter_bridge`, the one-shot `create`/`spawner` nodes,
  `controller_manager`) launches.
- `ros2 topic echo`/`ros2 topic info` both expose a `--no-daemon` flag
  (spins up their own throwaway rclpy context instead of the shared
  daemon) -- tested directly, works reliably even while the shared
  daemon is confirmed broken.
- `ros2 control list_controllers` has **no** `--no-daemon` flag at all
  (confirmed both via `--help` and by reading
  `ros2controlcli.verb.list_controllers`'s source: it imports
  `add_arguments` from `ros2cli.node.direct`, which only adds
  `--spin-time`/`--use-sim-time`, not the daemon toggle `ros2cli.node.
  strategy`'s topic verbs expose) -- so it cannot be fixed the same way.

**Fix** (asked the user first, since it meant touching
`run_clean_experiment.sh`, which DIAG-001's own spec had originally
marked read-only -- approved explicitly): added `--no-daemon` to the
`/clock`, `/joint_states`, and `/effort_controller/commands` topic-info
checks, and replaced the `ros2 control list_controllers` call with a
small inline rclpy script that calls the `ListControllers` service
directly (`_list_controllers_direct`, bypassing `ros2cli`'s daemon/
NodeStrategy machinery entirely). Verified end-to-end immediately after:
the same `lqr nominal_balance` invocation that had failed 5/5 times
before now completes fully in ~28s (previously timed out at ~55s every
time), all the way through a real scenario result. This fix is documented
in `run_clean_experiment.sh`'s own header comment (dated, with the full
root-cause chain) so it's legible to whoever reads that script next, not
just here.

# Method

`tasks/DIAG-001-timing-jitter/scripts/measure_jitter.py`: a standalone
rclpy node (not part of any ROS2 package), subscribes to `/joint_states`
and `/effort_controller/commands`, records `time.monotonic()` wall-clock
arrival time for every message on both topics, plus each `JointState`
message's `header.stamp` (sim time) for reference. `Float64MultiArray`
(the command message type) carries no header/stamp, so only wall-clock
receipt time is available for it.

`tasks/DIAG-001-timing-jitter/scripts/run_diag001.sh`: orchestrates N
clean `lqr nominal_balance` runs via the existing, unmodified (beyond the
daemon fix above) `run_clean_experiment.sh`, launching `measure_jitter.py`
concurrently with each run's active experiment window (watches the
clean-experiment log for `[4/4] Running experiment`, then records for
9.0s -- covers `nominal_balance.yaml`'s `settle_time_before_s=1.0` +
`total_duration_s=6.0` = 7.0s scenario window, plus a 2s buffer).

`tasks/DIAG-001-timing-jitter/scripts/compute_jitter_stats.py`:
aggregates the N raw per-run timestamp files into per-topic interval
statistics (mean, std, p95/p99/max absolute deviation from the nominal
period). Deliberately does not judge "jitter is significant" -- per
`LQI_ROOT_CAUSE_PLAN.md`'s explicit instruction, that call is deferred to
Task B (`PHYS-002`).

N=5 real runs, each a genuine, freshly-launched Gazebo instance (no
in-process repeats -- same precedent `PHYS-001`/`ENV-001` already
established for this environment).

# Results (real numbers, N=5)

| run | joint_states mean/std (ms) | joint_states p99/max dev (ms) | commands mean/std (ms) | commands p99/max dev (ms) |
|---|---|---|---|---|
| 1 | 5.010 / 0.430 | 1.495 / 3.263 | 10.000 / 0.430 | 1.333 / 2.161 |
| 2 | 5.096 / 0.753 | 3.329 / 9.300 | 10.001 / 0.400 | 1.395 / 3.272 |
| 3 | 5.009 / 0.354 | 1.233 / 3.479 |  9.999 / 0.366 | 1.271 / 1.630 |
| 4 | 5.070 / 0.583 | 1.580 / 6.780 |  9.826 / 1.322 | 9.367 / 9.509 |
| 5 | 5.056 / 0.688 | 2.220 / 8.607 | 10.000 / 0.570 | 2.407 / 3.493 |

Nominal periods: `/joint_states` 5ms (controller_manager 200Hz),
`/effort_controller/commands` 10ms (lqr_node.py's own 100Hz timer).

Aggregate across runs: mean of per-run std -- `/joint_states`
**0.562ms**, `/effort_controller/commands` **0.618ms**.

Sim-time-vs-wall-clock spacing (joint_states only, since `header.stamp`
gives sim time): sim-time interval is exactly 5.0000ms in every single
run (Gazebo's own step is perfectly regular, as expected -- no jitter
exists on the simulated-time side by construction), while the
*wall-clock* interval averages 5.009-5.096ms across runs -- a small
(~0.2-2%) but real and consistent overshoot versus nominal, on top of
whatever variance shows up per-sample.

Full per-run and per-topic numbers: `evidence/jitter_stats.json`,
raw per-message timestamps: `evidence/run_<i>_raw_timestamps.json`.

# What this does and doesn't establish (plain, not pre-judged)

Per `LQI_ROOT_CAUSE_PLAN.md`'s explicit instruction, this section states
the numbers plainly without deciding "jitter explains the slow
settling" -- that call is Task B's (`PHYS-002`), which can compare
against a jitter-free (physics-only, closed-loop) baseline directly.

**By the plan's own suggested std threshold** (std < 0.5ms ~=
negligible, std > 2ms ~= clearly significant, relative to the 5/10ms
nominal periods): the *mean* jitter (std of inter-arrival intervals) in
every single run sits in between those two markers -- mostly
0.35-0.75ms for `/joint_states`, 0.37-0.57ms for
`/effort_controller/commands` in 4 of 5 runs, with one outlier run
(#4) at 1.32ms for commands. None reach the plan's ">2ms = clearly
significant" bar on the std measure alone.

**However, worst-case (not mean) jitter is much larger and not
obviously negligible**: p99 deviation from nominal reaches 2.2-3.3ms
for `/joint_states` in most runs (up to 3.3ms/66% of the 5ms period),
and max single-sample deviation reaches 6.8-9.3ms in 3 of 5 runs --
i.e. occasional individual samples arrive nearly a full nominal period
late (or early). For `/effort_controller/commands`, run #4 shows a
9.5ms max deviation on a 10ms nominal period -- essentially a full
missed/doubled tick at least once during that run.

This matters specifically because of how `lqr_node.py`'s own integrator
is implemented (confirmed by reading `_on_timer` directly): `self.qi1 +=
q1 * self.dt`, where `self.dt = 1.0 / rate_hz` is the *fixed nominal*
timestep (10ms), never the actual elapsed wall-clock time since the
previous timer firing. If a single timer callback fires ~9ms late (as
observed in run #4's max deviation), the integrator still assumes
exactly 10ms passed, when actually ~19ms did -- a real, one-off
model-mismatch in the integral state on that specific step, not merely
"jitter that averages out." Whether occasional errors of this size,
happening a handful of times over a 6-7s run, are large enough to
explain multiple seconds of extra settling time is exactly the open
question Task B is designed to answer -- not decided here.

# Completion (per specification.yaml's acceptance criteria)

- [x] N=5 real LQR/nominal_balance runs, each with a concurrently-recorded
  raw timestamp file for both topics.
- [x] Per-topic jitter statistics computed and saved to
  `evidence/jitter_stats.json`.
- [x] Plain, non-prejudged statement of measured jitter magnitude vs. the
  plan's suggested std thresholds, with the mean/worst-case distinction
  made explicit (see above) -- significance judgment deferred to
  `PHYS-002` as instructed.

# Next: Task B (`PHYS-002`)

Per `LQI_ROOT_CAUSE_PLAN.md`'s stated order, proceed to `PHYS-002`
(closed-loop physics-only harness: run the *same* cached LQI gains,
`lqr_controller.py`/`plant_params.py` logic, directly against
gz-transport with an exact fixed 10ms step -- no ROS2/DDS, no jitter by
construction) and compare its settling time against both this jitter
data and the ROS end-to-end settling time already on record (~3.3-3.4s,
vs. the offline linear model's ~0.63s prediction).
