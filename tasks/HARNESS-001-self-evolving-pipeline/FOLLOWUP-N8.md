# Follow-up: larger-N severity comparison (2026-08-22)

## Why

HARNESS-001's original N=3-per-condition comparison found a catastrophic
failure (torque saturation / instability) in the mismatched conditions
(BENCH-001, BENCH-003) but not in a matched control -- suggesting the
plant/model mismatch had a real physical effect distinct from the
already-known CTRL-003 variance. N=3 is too small to trust that pattern,
so this follow-up reruns baseline (mismatch, no skill) and candidate
(mismatch, skill applied) at N=8 each, using a `catastrophic_rate` metric
(stable=false OR overshoot >100 deg on either joint) instead of the raw
pass/fail threshold, which nominal_balance fails almost universally
regardless of mismatch (see CTRL-003/004).

## What happened

**Environment note**: this follow-up was interrupted twice by what
appeared to be background-task-tracking instability in the tool session
(tasks reported "killed" well before their expected duration, in one case
after a real ~27-hour wall-clock gap from a WSL/machine sleep). Investigation
found the underlying WSL processes are NOT actually killed when this
happens for a *looped* script (`run_repeated_experiment.sh` itself), but
its early prematurely-killed attempts kept running undetected in the
background and their orphaned processes (`parameter_bridge`,
`robot_state_publisher`) later collided with fresh runs, corrupting one
data point (a stale result.json got silently copied twice -- fixed in
`_manual_repeat_helper.sh` by checking run_clean_experiment.sh's own exit
code and retrying on infra-failure exit codes instead of trusting file
existence). Final data below is from fully-clean, individually-verified
foreground runs (`run_clean_experiment.sh` called directly per run,
sequentially, not through the background-task mechanism).

## Results

| condition | N | catastrophic_rate | overshoot_q1 range (non-catastrophic runs) |
|---|---|---|---|
| baseline (m2=1.4, no model regen) | 8 | **0/8 (0%)** | 16.2 - 18.6 deg |
| candidate (m2=1.4, model regenerated) | 8 | **1/8 (12%)** | 14.5 - 15.0 deg |

Raw data: `evidence/followup_n8/*_baseline.json`, `*_candidate.json`.

## Conclusion

This REVISES the original HARNESS-001 conclusion. With a larger, more
carefully-controlled sample:

1. **The baseline mismatch (m2=1.4, uncorrected model) showed ZERO
   catastrophic failures across 8 runs** -- unlike the N=3 test, which
   showed 1/3. This means the earlier claim ("the mismatch has a real,
   distinct physical effect visible as catastrophic instability, unlike a
   matched control") does not hold up under more data. The 1-in-3
   catastrophic result in BENCH-001 was more likely an instance of
   CTRL-003's still-unexplained run-to-run chaotic variance than a
   repeatable consequence of the mass mismatch itself.
2. **The candidate (skill applied) showed MORE catastrophic failures than
   baseline this time (1/8 vs 0/8)** -- the opposite direction from what
   the skill is supposed to achieve. At N=8 this is still consistent with
   pure chance (a single event), not evidence the skill makes things
   worse. But it definitively does not support promotion either.
3. **The skill's non-catastrophic-run overshoot IS mildly, consistently
   lower with the model correction** (14.5-15.0 deg vs 16.2-18.6 deg) --
   a small, repeatable improvement in the "normal" case, just not large
   enough or reliable enough to prevent the rare catastrophic event, and
   not something the original binary pass/fail or catastrophic-rate metric
   was designed to credit.
4. **`promote_skill.py`'s REJECT decision stands, and for a clearer reason
   now**: not "no measurable effect" (the original, weaker finding) but
   "no measurable reduction in the failure mode that matters, despite a
   real N=8 comparison, plus a same-direction-as-baseline residual
   catastrophic-failure rate that this experiment cannot attribute to the
   mismatch at all." The honest state of this investigation is: the
   catastrophic failure mode's root cause remains unidentified (most likely
   the same unresolved chaotic-timing-sensitivity question from CTRL-003),
   and the mismatch's real, distinguishable effect -- if it exists -- is
   the smaller, consistent overshoot difference in the non-catastrophic
   case, not the catastrophic tail event this investigation originally
   focused on.

## Process lessons (for future repeated-benchmark tasks)

- `run_in_background` for a long (multi-minute) looped shell script became
  unreliable in this session after a long real-world idle gap -- tasks get
  marked "killed" well before completion. Workaround: drive the repeat loop
  from sequential **foreground** Bash calls instead (confirmed reliable),
  saving each run's result.json manually.
- Always check the driving script's own exit code before trusting a
  "result saved" step -- a stale file from a previous run can silently
  masquerade as a new one if the new run aborted before writing it.
- After any interrupted/killed background attempt, check for orphaned
  processes broadly (`parameter_bridge`, `robot_state_publisher`, not just
  `gz sim`) before trusting a "clean" environment for the next run.
