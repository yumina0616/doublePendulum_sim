# Goal

Add a machine-readable suite-level `summary.json` output to
`run_regression_suite.sh`, so the pass/fail result of a full regression run
can be consumed by other tooling instead of only being printed to a
terminal.

# Observed baseline

`run_regression_suite.sh pd` (run 2026-08-21) executes all 3 scenarios and
prints a human-readable table:

```
  impulse_disturbance       PASS
  initial_angle_small       FAIL (exit 1)
  nominal_balance           FAIL (exit 1)
SOME SCENARIOS FAILED
```

but nothing is written to disk at the *suite* level (each scenario already
writes its own `/tmp/<scenario>_result.json` via `run_experiment.py`, but
there is no single "did the whole suite pass" artifact).

# Hypothesis

A small addition to the existing bash loop -- accumulate pass/fail into an
associative array (already exists as `RESULT`), then serialize it to JSON
at the end -- is sufficient. No changes to `run_experiment.py` or
`metrics.py` are needed; this is purely a `run_regression_suite.sh`
presentation-layer change.

# Proposed work

1. Add a `--output <path>` option to `run_regression_suite.sh` (default
   `/tmp/regression_summary.json`).
2. After the existing summary table printing, build and write a JSON
   object: `{"controller": ..., "timestamp": ..., "scenarios": {name:
   "PASS"|"FAIL", ...}, "overall_pass": true|false}`.
3. Do not touch the existing stdout table or exit-code logic.
4. Run `run_regression_suite.sh pd` and confirm:
   - stdout table is byte-for-byte the same shape as the baseline above
   - `/tmp/regression_summary.json` exists and has the expected structure
   - exit code is still 1 (since PD still fails 2/3 scenarios) -- this
     script's job is to report status accurately, not to make PD pass.

# Acceptance Criteria

- `summary.json` written with the fields listed above
- exit code unchanged (0 iff every scenario passed)
- stdout output unchanged
- regression: `run_regression_suite.sh pd` still runs all 3 scenarios
