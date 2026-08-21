# Goal

Root-cause why identical repeated runs of the same scenario/controller/gains
produce wildly different physics outcomes.

# Observed baseline

From CTRL-002's verification (2026-08-21), two back-to-back clean runs of
`run_clean_experiment.sh pd nominal_balance` (spawn race already fixed):

| run | overshoot_q1_deg | overshoot_q2_deg | stable |
|---|---|---|---|
| 1 | 200.49 | 154.82 | false |
| 2 | 26.78  | 23.70  | true  |

Also seen earlier with `impulse_disturbance`: overshoot_q1_deg at 23.8 (an
early PASS), 117.7, and 135.0 across different runs of the same scenario.

# Hypothesis

The world file (`empty_world.sdf`) sets `real_time_factor=1.0`, meaning
Gazebo throttles physics stepping to track wall-clock time. The
disturbance wrench is applied by `run_experiment.py`'s own `rclpy` timer
(`settle_before <= t`, `t` derived from `self.get_clock().now()`), and the
LQR/PD controllers publish on their own independent wall-clock timers too.
None of these are synchronized to Gazebo's *simulation* clock ticks --
they're all real-time-scheduled. If OS scheduling jitter (WSL2, shared
with the user's other work) shifts *when within a physics step* the wrench
gets applied or a control command lands, and this system is only weakly
damped / operating close to a stability boundary for these disturbance
magnitudes, a few-millisecond shift in timing could plausibly cascade into
a qualitatively different trajectory (this is consistent with, but not
proof of, either real chaos or a timing bug -- distinguishing those is
exactly what this task needs to do).

Testable prediction: if wall-clock/real-time-factor pacing jitter is the
(or a) driver, then running with a much higher (or effectively unbounded)
`real_time_factor` -- so Gazebo just runs physics steps as fast as
possible instead of throttling to match wall-clock time -- should *reduce*
run-to-run variance, because the control loop's timers would then be
racing against a much more predictable, fast-forwarding sim clock instead
of real-time OS scheduling.

# Proposed work

1. Run `nominal_balance` with PD, same gains, 3 times back-to-back (already
   have 2 from CTRL-002 evidence; get a 3rd) to quantify baseline variance.
2. Temporarily raise `real_time_factor` in `empty_world.sdf` (e.g. to a
   large value or Gazebo's "unthrottled" setting) and repeat the same 3
   runs. Compare variance.
3. If variance drops significantly with unthrottled real-time-factor:
   root cause = (a) wall-clock pacing jitter. Decide whether to ship the
   unthrottled setting permanently (trade-off: simulation runs faster than
   real-time, which is fine for automated testing but means a human
   watching the GUI would see it play out "too fast").
4. If variance persists similarly either way: root cause is likely (b)
   genuine chaotic sensitivity or (c) a physics-solver non-determinism
   unrelated to real-time pacing. Document this clearly; do not attempt
   further fixes without new evidence pointing somewhere specific.
5. Write up findings either way, update private/roadmap.md.

# Acceptance Criteria

See specification.yaml.
