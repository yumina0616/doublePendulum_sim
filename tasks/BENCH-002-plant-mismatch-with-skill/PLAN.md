# Goal

Demonstrate the candidate skill's fix for BENCH-001's plant/model mismatch:
regenerate `linear_model.py`'s `PendulumParams` to match the real plant
(m2=1.4), then re-run the identical statistical benchmark, and compare
pass rates against BENCH-001 as the regression gate for promotion.

# Proposed work

1. `linear_model.py`: `PendulumParams.m2` default 1.0 -> 1.4 (xacro already
   at 1.4 from BENCH-001, left in place).
2. No change needed to `lqr_controller.py` -- `design_lqr()` calls
   `DoublePendulum(params)` -> `linearize()` fresh every time `lqr_node.py`
   starts, so the next controller launch automatically re-linearizes and
   re-solves the CARE equation with the corrected mass.
3. Run `run_repeated_experiment.sh lqr nominal_balance 3 0.6`, same
   scenario/N/threshold as BENCH-001 for a fair comparison.
4. Feed both summaries into `harness/promote_skill.py` for the actual
   promote/reject decision.

# Acceptance Criteria

See specification.yaml. The comparison against BENCH-001 (not a fixed
absolute bar) is what determines promote/reject.
