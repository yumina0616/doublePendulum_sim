# Goal

Generate real failure evidence for HARNESS-001's failure store: change the
plant (link2 mass 1.0 -> 1.4 kg in the xacro) without regenerating the
controller's linear model, run the existing statistical acceptance tool
(CTRL-004) against LQR/nominal_balance, and record whatever pass rate
actually results -- no cherry-picking.

# Proposed work

1. `double_pendulum.urdf.xacro`: `m2` 1.0 -> 1.4.
2. `linear_model.py`: untouched (still assumes m2=1.0 -- this is the bug
   being demonstrated).
3. Run `run_repeated_experiment.sh lqr nominal_balance 3 0.6`.
4. Record the resulting `/tmp/repeated_nominal_balance_summary.json` as
   this task's evidence.

# Acceptance Criteria

See specification.yaml. A low pass rate is the *expected and desired*
outcome here (it's the failure this benchmark exists to capture) -- record
it honestly either way.
