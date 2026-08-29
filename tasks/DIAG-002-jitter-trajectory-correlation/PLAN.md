# DIAG-002: when/how does the real trajectory diverge from physics-only?

## Goal

PHYS-002 established that real ROS2 e2e is qualitatively worse than
physics-only (never settles vs. settles cleanly at 3.24s), and CTRL-006
established that fixing the offline/physics-only gain doesn't fix this
and can worsen it. Neither pinned down *when* or *how* the real
trajectory actually departs from what jitter-free physics predicts, or
whether that departure lines up with individual large jitter events
(the mechanism DIAG-001 measured but didn't connect to an outcome).
This task does that, using the original (pre-CTRL-006, currently
deployed) gain -- the same one PHYS-002's physics-only reference used.

## Method

`record_trajectory.py`: extends DIAG-001's `measure_jitter.py` to also
record actual `/joint_states` positions and `/effort_controller/commands`
values, using `run_experiment.py`'s exact `_now_s()`/`self.t0` convention
(wall-clock seconds since the first real `/joint_states` message) so
this recording's `t` axis is directly comparable to every other
`settling_time_*` calculation in this project, and to PHYS-002's
physics-only `t` (equivalent under this world's `real_time_factor=1.0`).
Same raw wall-clock arrival timestamps DIAG-001 used are recorded too,
on this exact same run -- no need to reconcile two separate recordings'
timelines.

N=5 attempted via `run_diag002.sh` (DIAG-001's orchestration pattern,
reused verbatim) against `run_clean_experiment.sh lqr nominal_balance`
(unmodified). Run 1 hit a plain infra hiccup (never reached
`[4/4] Running experiment`, excluded honestly, not counted). Runs 2-5
all recorded successfully (1341-1465 `/joint_states` samples,
674-737 command samples each).

`correlate_trajectory_jitter.py`: interpolates PHYS-002's physics-only
reference trajectory (`evidence/physics_only_run_1.json`, run 1 of 5 --
all 5 were bit-identical, so any one serves as ground truth) onto each
real run's actual sample times, computes `|real - physics_only|` in
degrees over time, and finds the **divergence onset**: the first
`t >= settle_before_s` after which that divergence stays above 1.0deg
(matching `settle_band_deg`) for the rest of the recording -- i.e. the
mirror image of `metrics.py`'s own `settling_time` definition, applied
to "stops tracking the ideal" instead of "settles".

## Results

| run | onset_t | max div q1 (deg) | max div q2 (deg) | largest jitter event (t, deviation) |
|---|---|---|---|---|
| 2 | 3.881 | 17.86 | 4.26 | t=4.455, 4.13ms |
| 3 | 3.315 | 17.30 | 8.48 | t=6.518, 6.89ms |
| 4 | 3.877 | 17.80 | 5.40 | t=2.757, 11.09ms |
| 5 | 3.953 | 17.81 | 5.16 | t=6.091, 3.34ms |

**Divergence onset is NOT near each run's own single largest jitter
event, in 4/4 runs** (all `|onset_t - largest_jitter_t| > 0.2s`; some
are seconds apart, e.g. run 4's biggest jitter spike at t=2.76s is 1.1s
*before* its onset at t=3.88s).

**But divergence onset clusters tightly right after physics-only's own
settling time (3.24s)**: `+0.075s, +0.637s, +0.641s, +0.713s` across the
4 runs (mean `+0.516s`), a **much** tighter and more consistent pattern
than the largest-jitter-event timing, which varies across a wide,
inconsistent range (2.76s-6.52s) with no shared value across runs.

Full numbers: `evidence/correlation.json`, `evidence/run_{2..5}_raw_trajectory.json`.

## Interpretation -- reported honestly, including the null result

- **No support for "one big jitter spike breaks it"**: the specific
  timing of each run's largest single arrival-jitter event does not
  predict when that run's trajectory actually departs from the ideal.
  This null result is itself useful -- it argues against a simple
  "delay event exceeds some threshold and the loop falls over"
  mechanism, at least at the single-largest-event level tested here.
- **Divergence onset instead lines up consistently with physics-only's
  own settling moment**, not with anything specific to each run's own
  jitter realization. A plausible mechanism: this gain (already known,
  from PHYS-002/CTRL-006, to be only marginally able to settle at all,
  and to get *more* fragile under a more aggressive re-tune) is exactly
  at its most sensitive right around the moment it would otherwise
  cross into the settle band -- small, cumulative jitter effects
  (not one dramatic event) are enough to nudge it away from actually
  entering/staying in that band at the critical moment, and once it
  misses, the marginal design doesn't recover. This fits the
  "compounding small jitter, not a single spike" framing DIAG-001's own
  interpretation section already raised as a live possibility.
- This is a **plausible mechanism, not a proven one** -- N=4 valid runs,
  one gain, one scenario. It does explain why the onset timing clusters
  so tightly despite each run's jitter realization being essentially
  independent, which the "single big spike" hypothesis does not explain
  at all.

## Completion checklist (against specification.yaml's acceptance)

- [x] N=5 attempted, 1 honest infra exclusion, 4 valid recorded runs
- [x] divergence-onset time computed per valid run
- [x] checked against each run's own largest jitter event (result: no correlation)
- [x] checked against physics-only's own settling time (result: tight clustering) -- not originally required by the spec, added because the numbers pointed there
- [x] null result (no single-event correlation) reported as a real finding, not discarded

## Next

- The "compounding small jitter near the marginal settling boundary"
  mechanism is a hypothesis, not yet a proof. A more direct test: rerun
  the physics-only harness with a synthetic, controllable jitter
  injected onto its 10ms control period (drawn from DIAG-001's actual
  measured jitter distribution, or simple worst-case-magnitude
  injections) and see whether physics-only starts failing to settle in
  the same way -- this would isolate jitter as sufficient, without any
  other confound the real ROS2/DDS path carries.
- A gain search with an explicit delay/jitter-robustness objective
  (per CTRL-006's own next-step note) is a complementary path, and this
  task's finding narrows what such an objective should target:
  robustness specifically around the moment the loop would otherwise
  settle, not overall aggressiveness.
