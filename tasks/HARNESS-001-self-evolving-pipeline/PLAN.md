# Goal

Build Phase 6 (Self-Evolving Harness) end-to-end, using project_plan.md's
own worked example (section 11.1): plant parameter changed, controller
model not regenerated, repeated FAIL pattern -> proposed skill ->
regression-gated promotion.

# Why this scenario specifically

Confirmed by reading the code: `double_pendulum.urdf.xacro` defines
`m1/m2/L1/L2` as independent xacro properties, and
`linear_model.py`'s `PendulumParams` dataclass hardcodes its own
`m1=m2=L1=L2=1.0` defaults. Nothing keeps them in sync -- changing one
without the other is a real, reproducible mismatch, not a fabricated
scenario. Both are symlink-installed (`install/.../urdf/*.xacro` links back
to `src/`), so xacro edits take effect on the next launch with no colcon
build needed.

# Proposed work

1. **Benchmark A (baseline, no skill)**: edit xacro `m2` 1.0 -> 1.4 only.
   Run `run_repeated_experiment.sh lqr nominal_balance 3 0.6`. Record as
   `tasks/BENCH-001-plant-mass-mismatch/` (own spec+plan+result, same
   agentic-task format as CTRL-*). This is real evidence of a plant/model
   mismatch failure.
2. **Benchmark B (candidate skill applied)**: keeping xacro `m2=1.4`, also
   update `linear_model.py`'s `PendulumParams.m2` default to 1.4 (this IS
   the skill's procedure: "detect plant parameter change -> regenerate
   linear model -> recompute controller gain -> re-run"). Run the same
   `run_repeated_experiment.sh lqr nominal_balance 3 0.6`. Record as
   `tasks/BENCH-002-plant-mismatch-with-skill/`.
3. Revert both files to `m1=m2=L1=L2=1.0` immediately after B's run
   completes -- confirmed via `git diff`.
4. **harness/failure_store.py**: scan `tasks/*/result.json` (passed=false),
   cross-reference each task's `specification.yaml` `allowed_changes` for
   which files were touched, write `harness/failure_store.jsonl`.
5. **harness/categorize_failures.py**: rule -- a failure whose
   allowed_changes touch `*.xacro`/`*.urdf` but NOT
   `linear_model.py`/`lqr_controller.py`/`pd_controller.py` in the same
   task is category `plant-model-inconsistency`. Output
   `harness/failure_categories.json`.
6. **harness/propose_skill.py**: for any category with >=2 evidence
   entries, emit `harness/skills/candidates/<ID>.yaml` matching section
   11.1's schema (id/trigger/procedure/reason/evidence).
7. **harness/promote_skill.py**: read Benchmark A's and B's
   `/tmp/repeated_*_summary.json` pass rates, apply promotion gate
   (candidate pass_rate > baseline pass_rate, per section 12's spirit --
   simplified since we don't have a large benchmark suite for the full
   token-cost/tool-call metrics yet). PROMOTE moves the skill YAML to
   `harness/skills/active/` and adds metadata (status, created_from,
   activation_count=1, last_verified=<task_id>, per section 13's schema).
   REJECT leaves it in candidates/ with a rejection reason recorded.

# Acceptance Criteria

See specification.yaml. Must not force a promotion if B doesn't actually
beat A -- an honest REJECT is a valid, acceptable outcome (same principle
CTRL-003/004 already established for this project).

# Known risk

CTRL-003/004 already found substantial run-to-run physics variance even in
the *matched* (no mismatch) case. N=3 per condition may not cleanly
separate "mismatch effect" from "background variance" -- if results are
ambiguous, report that honestly rather than cherry-picking a threshold
that produces a clean-looking PROMOTE.
