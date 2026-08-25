# Goal

Per `private/NEXT_STEPS.md` item 3-1: split the current plain pass/fail
bool into a 4-way verdict taxonomy so `pass_rate` numbers can no longer
be silently poisoned by infra failures (a discovery timeout, zero real
torque) masquerading as control failures.

# Design

```text
PASS_CONTROL    -- experiment completed normally, met acceptance criteria
FAIL_CONTROL    -- experiment completed normally, missed acceptance criteria
INVALID_INFRA   -- experiment never validly ran (0 samples, 0 torque,
                   discovery timeout, controller/LQR never became ready)
FAIL_HARNESS    -- the harness/tooling itself broke (uncaught exception,
                   bad CLI usage) -- not a physics or infra timing issue
```

`INVALID_INFRA` and `FAIL_HARNESS` are excluded from `pass_rate`'s
denominator; both are reported separately as rates of their own
(`infra_failure_rate`, `harness_failure_rate`) so infra flakiness stays
visible instead of just disappearing from the sample.

# Implementation

1. **`metrics.py`**: added `classify_verdict(metrics, passed,
   n_samples_joint_states, n_samples_effort) -> str`. Rule (deliberately
   simple/auditable, not a fuzzy heuristic): `INVALID_INFRA` if either
   sample count is 0, or if commanded torque was 0 on both joints for the
   entire run (the zero-torque case CTRL-004 first observed and CTRL-005
   root-caused to the controller-readiness race). Otherwise
   `PASS_CONTROL`/`FAIL_CONTROL` from the existing acceptance check.
   `FAIL_HARNESS` is not decided here -- it's for a caller to set directly
   when a run never reaches this function at all.

2. **`run_experiment.py`**:
   - `_finalize()` now calls `classify_verdict` and writes `verdict` into
     `result.json`.
   - Result writes go through a new `write_result_json()` that does
     temp-file + `os.replace()` (atomic on POSIX) instead of a direct
     `open(...).write()`, so a kill mid-write can't leave a half-written
     JSON file for a downstream reader to choke on.
   - The discovery-timeout path (`SystemExit(6)`) previously logged an
     error and exited with **no result.json at all**. It now calls
     `write_infra_failure_result(..., VERDICT_INVALID_INFRA, ...)` first,
     so downstream aggregation always finds a verdict-tagged artifact
     regardless of which stage failed.
   - Added a top-level `except Exception` around the spin loop that
     writes `VERDICT_FAIL_HARNESS` with the traceback and exits 7 -- a
     genuine harness bug is no longer indistinguishable from a physics
     result or a plain crash with no artifact.

3. **`run_clean_experiment.sh`**: every one of its own pre-flight abort
   paths (unknown controller = exit 2, LQR not ready = exit 3, no
   `/joint_states` = exit 4, controller command topic never discovered =
   exit 5) previously wrote nothing but a stderr message. Added
   `write_infra_abort_result()` (shells out to `python3 -c` to build the
   same JSON shape `run_experiment.py` writes) and call it before each
   abort, so every failure mode -- however early -- leaves one consistent
   verdict-tagged `result.json` behind. Exit 2 (bad controller name, a
   usage error) is tagged `FAIL_HARNESS`; exits 3/4/5 are tagged
   `INVALID_INFRA`.

4. **`run_repeated_experiment.sh`**: added `read_verdict()`, which reads
   the `verdict` field out of each run's `result.json` (falling back to a
   coarse exit-code inference only if the field is somehow missing --
   robustness against a stale/foreign file, not the normal path). Now
   tracks `n_pass_control` / `n_fail_control` / `n_invalid_infra` /
   `n_fail_harness` separately, computes `pass_rate` only over
   `n_pass_control + n_fail_control`, and reports `infra_failure_rate` /
   `harness_failure_rate` as separate fields in
   `repeated_<scenario>_summary.json`. If every single run in a batch
   comes back `INVALID_INFRA`/`FAIL_HARNESS` (denominator 0), the overall
   verdict is `INCONCLUSIVE_NO_VALID_RUNS` rather than a misleading plain
   `FAIL` -- there is no control result to judge in that case at all.

# Verification (real runs, not synthetic)

Single clean run (`pd`/`nominal_balance`):

```text
verdict=FAIL_CONTROL, passed=false, n_samples_joint_states=875
failures: settling_time_q1_s/q2_s both exceed the 3.0s max
  (consistent with CTRL-005's already-documented gain-tuning gap)
```

`run_repeated_experiment.sh pd nominal_balance 3 0.6` (N=3, real Gazebo
runs, no synthetic data) -- see `evidence/n3_summary.json` and
`evidence/n3_run{1,2,3}_result.json`:

| run | verdict | reason |
|---|---|---|
| 1 | FAIL_CONTROL | settling_time_q1_s=3.24s, q2_s=3.31s (>3.0s max) |
| 2 | INVALID_INFRA | no /joint_states data within 60s of Gazebo launch |
| 3 | FAIL_CONTROL | settling_time_q1_s=3.36s, q2_s=3.43s (>3.0s max) |

Aggregate: `n_pass_control=0, n_fail_control=2, n_invalid_infra=1,
n_fail_harness=0`, `pass_rate=0.0` computed over the 2 control runs only
(not diluted or inflated by the infra failure), `infra_failure_rate=0.33`
reported separately, overall verdict `FAIL` (not `INCONCLUSIVE`, since 2
valid control runs did exist).

This is exactly the failure mode INFRA-001 was built to catch: run 2's
Gazebo launch never got `/joint_states` flowing at all (almost certainly
the FastRTPS `/dev/shm` accumulation factor CTRL-005 already documented
as a known, real, not-permanently-fixed environmental issue) -- and it
was automatically classified `INVALID_INFRA` and excluded from
`pass_rate`, instead of silently counting as "the controller failed."

# Conclusion

`pass_rate` numbers reported from this point on (in this task and any
that build on `run_repeated_experiment.sh`) are no longer a mix of
control quality and infra flakiness. The two remaining FAIL_CONTROL
results in the N=3 batch are consistent with CTRL-005's already-honest
conclusion: `pd`/`nominal_balance`'s settling time is a genuine,
ordinary ~10-15% gain-tuning gap, not a reproducibility mystery. This
task does not attempt to close that gap -- it only makes the
measurement of it trustworthy, which is the stated precondition in
`NEXT_STEPS.md` before any of items 4-6 (physics-only mode, distro
comparison, plant_params refactor) can be trusted either.

INFRA-002 (full 6-condition readiness state machine) and INFRA-003 (run
isolation: unique run_id/ROS_DOMAIN_ID, atomic writes already partly
covered here, environment manifest) are separate, not-yet-started tasks
per `NEXT_STEPS.md`'s own scoping.
