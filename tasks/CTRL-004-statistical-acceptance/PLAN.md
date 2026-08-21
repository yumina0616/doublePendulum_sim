# Goal

Add a statistical acceptance mode (run N times, require a pass rate) as a
practical workaround for the unresolved run-to-run physics variance found
in CTRL-003.

# Observed baseline

CTRL-003: 3 identical wall-clock runs of pd/nominal_balance gave
overshoot_q1_deg = 200.5, 26.8, 63.9 -- i.e. this specific scenario fails
2 of 3 times under the current (30 deg) bound, but isn't uniformly broken
either. A single-run verdict is not trustworthy for this case.

# Proposed work

1. `run_repeated_experiment.sh <pd|lqr> <scenario> [N] [threshold] [-- extra args]`:
   loop `run_clean_experiment.sh` N times (default 5), collect each run's
   exit code, compute pass_rate = passes/N.
2. Verdict: PASS if pass_rate >= threshold (default 0.6), else FAIL.
   Exit code 0/1 accordingly.
3. Write `/tmp/repeated_<scenario>_summary.json`:
   `{controller, scenario, n_runs, n_passed, pass_rate, threshold, verdict}`.
4. Verify against pd/nominal_balance (N=5) -- expect a mixed pass/fail
   pattern given CTRL-003's data, and a sensible final verdict either way.

# Acceptance Criteria

See specification.yaml. Note this task's job is to build a working,
verified TOOL -- it is not trying to make PD "pass" nominal_balance, and
must not report a false overall PASS if the majority of runs actually
fail.
