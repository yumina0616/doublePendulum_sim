# CTRL-006: LQI Q/R gain re-search (Case 1 follow-up to PHYS-002)

## Goal

PHYS-002 found the current LQI gain (`q=(50,50,5,5,10,10) r=(0.05,0.05)`)
marginally fails the 3.0s settling spec even offline/physics-only
(Case 1), separately from a further real ROS2/DDS degradation (Case 2).
This task re-searches Q/R weights to fix the Case 1 portion, and
verifies with real Gazebo runs whether that offline improvement actually
translates to better real behavior.

## Pre-existing bug found: `autotune_lqr.py`'s search was broken since REFACTOR-001

`main()` called `DoublePendulum(PendulumParams())` -- `PendulumParams()`
with no constructor args, which raises `TypeError` since REFACTOR-001
changed `PendulumParams` to require explicit fields loaded from
`plant_params.yaml`. Every other caller in the codebase uses
`DoublePendulum()` (which internally calls `PendulumParams.load()`).
This means the search itself could not have been successfully run since
REFACTOR-001 landed -- fixed to `DoublePendulum()`, kept regardless of
which gain this task deploys.

## Search

`autotune_lqr.py --scenario nominal_balance` (defaults: maxiter=40,
popsize=15), against the current `plant_params.yaml`. Took **953.8s
(~16min)**. Result:

```
q1=187.0706  q2=174.4019  q1d=50.4355  q2d=3.2031  qi1=0.0059  qi2=11.0445  r1=0.0106  r2=0.0822
```

Offline sim: `PASS` -- `settling_time_q1_s=0.87, settling_time_q2_s=0.0,
overshoot_q1_deg=2.54, overshoot_q2_deg=0.79, final_q1_deg=-0.01`. A
dramatic offline improvement over the old gain's 3.25s.

## Verification

Deployed the new weights (`lqr_node.py`'s ROS-parameter defaults,
`design_lqr_gains.py`'s CLI defaults, regenerated the cache via
`ros2 run double_pendulum_control design_lqr_gains.py` so the actual
deployed cache matches), then verified with real runs, not just offline:

1. **Offline re-check** (this task's own copy of `offline_prediction.py`,
   `Q_DIAG`/`R_DIAG` constants updated): matches the search's own number
   (0.87s/0.0s) up to float noise from re-solving the CARE equation.
2. **Physics-only, N=3** (this task's own copy of
   `closed_loop_physics_only_runner.py`): all 3 runs **PASS_CONTROL**,
   `settling_time_q1_s=0.86` every run (deterministic, matching
   PHYS-002's established finding that this harness is bit-reproducible).
3. **Real ROS2 e2e, N=5** (`run_repeated_experiment.sh lqr
   nominal_balance 5 0.6`, unmodified): **0/5 PASS_CONTROL** --
   `settling_time_q1_s` in `{inf, 4.33, 5.00, inf, 4.84}`,
   `settling_time_q2_s` **Infinity in 5/5 runs**, overshoot
   `q1: 7.0-23.7deg`, `q2: 7.1-14.0deg`.

## Decision: revert to the original gain

Comparing real ROS2 e2e behavior, not just offline/physics-only, before
vs. after (both against the same real acceptance criterion this project
actually cares about):

| | old gain (PHYS-002's baseline, N=5, 4 valid) | new gain (this task, N=5) |
|---|---|---|
| q1 settling | Infinity, 4/4 valid runs | Infinity 2/5, else 4.33-4.99s |
| q2 settling | finite (2.7-2.8s) in 2/4 valid runs | **Infinity, 5/5 runs** |
| q1 overshoot | consistently ~16.3-16.5deg | more variable, 7.0-23.7deg |
| q2 overshoot | 2.2-7.1deg | **7.1-14.0deg, worse** |
| pass_rate | 0/4 valid | 0/5 |

Both gains fail the real acceptance test completely (0% pass rate
either way). The new gain does **not** fix the real-Gazebo problem, and
by several measures (q2 never settling at all, q2 overshoot roughly
doubling) it is **worse** in practice, despite being dramatically better
offline. This is consistent with normal control-theory intuition: a
more aggressive/faster gain (higher Q, lower R -- more feedback gain
overall) has less phase/delay margin, so it should be expected to be
*more* sensitive to the timing jitter/delay PHYS-002 already showed is
present in the real ROS2/DDS path, not less.

**Reverted** `lqr_node.py`/`design_lqr_gains.py` back to the original
defaults and regenerated the deployed cache to match (`git checkout --`
on both files, confirmed no other unintended changes reverted; the
`autotune_lqr.py` bug fix is unrelated and kept). Real production
behavior is unchanged from before this task; the new gain's full
numbers are preserved here and in `evidence/` as a negative result, not
discarded.

## Interpretation

This is itself useful evidence for PHYS-002's open question: fixing
Case 1 in isolation does not fix, and can make measurably worse, the
Case 2 symptoms. The two are not simply additive/independent in the way
the "Case 1 stacked under Case 2" framing suggested -- a Case-1 fix that
increases feedback aggressiveness actively fights against Case 2's
robustness margin. Any future gain search for this plant should treat
"how far the closed loop tolerates timing jitter/delay" (e.g. a
robustness/delay-margin term, or empirically re-verifying with the
physics-only harness's *jittered* variant once one exists) as a
first-class objective, not just offline settling time/overshoot -- an
offline-only cost function will keep finding gains like this one that
look excellent on paper and perform no better (or worse) for real.

## Completion checklist (against specification.yaml's acceptance)

- [x] one search run, weights + offline result recorded
- [x] offline verification matches the search's own result
- [x] N=3 physics-only verification runs
- [x] N=5 real ROS2 e2e verification runs
- [x] explicit keep-or-revert decision recorded with rationale (revert)
- [x] the non-deployed (new) gain's real numbers fully documented, not hidden

## Next

- A gain search that optimizes against real (or jittered-physics-only)
  behavior rather than the idealized offline/physics-only model is the
  natural next step for the Case 1 side of this investigation.
- PHYS-002's own Case 2 follow-up (correlating DIAG-001's jitter
  timestamps against exactly where the real trajectory diverges) is
  still the more direct path to actually fixing the real system --
  this task's finding argues it should come before any further gain
  search, not after.
