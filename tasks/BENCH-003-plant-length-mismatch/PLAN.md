# Goal

Provide a second, independent piece of real evidence for the
"plant-model-inconsistency" failure category, using a different plant
parameter (link1 length) than BENCH-001 (link2 mass), so
`propose_skill.py`'s min_evidence=2 threshold is met with genuine data
rather than lowered to fit one sample.

# Proposed work

1. `double_pendulum.urdf.xacro`: `L1` 1.0 -> 1.3.
2. `linear_model.py`: untouched (still assumes L1=1.0).
3. Run `run_repeated_experiment.sh lqr nominal_balance 3 0.6`.
4. Record the result as evidence, revert xacro immediately after.

# Acceptance Criteria

See specification.yaml. Record whatever pass rate actually results.
