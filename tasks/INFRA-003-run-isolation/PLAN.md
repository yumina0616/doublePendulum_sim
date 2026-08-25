# Goal

Per `private/NEXT_STEPS.md` item 3-3: stop overwriting result files
between runs/batches, record an environment manifest, isolate process
teardown, and (as asked) give each run its own `ROS_DOMAIN_ID`.

# Implementation

1. **`run_clean_experiment.sh`**: every invocation now computes a
   `RUN_ID` (`<controller>_<scenario>_<UTC timestamp>_<pid>`, or
   `DPEND_RUN_ID` if the caller sets one) and a `RUN_DIR`
   (`results/raw/<run_id>/`, or `DPEND_RUN_DIR` if set). `run_experiment.py`
   is now called with `--output "$RUN_DIR/result.json"` explicitly
   (previously no `--output` was passed at all -- it always wrote to the
   fixed `/tmp/<scenario>_result.json`, which every subsequent run
   overwrote). A `write_environment_manifest()` function writes
   `environment_manifest.json` into the same directory: `ROS_DISTRO`,
   `gz sim --version`, `use_sim_time`, and `physics_engine`/
   `max_step_size_s`/`real_time_factor` read directly out of
   `empty_world.sdf` (not hardcoded, so it can't silently drift out of
   sync with the actual world file). A best-effort copy to the old fixed
   `/tmp/<scenario>_result.json` path is kept for any existing manual
   workflow that still looks there -- the isolated directory is the
   source of truth now, never overwritten by a later run.

2. **`run_repeated_experiment.sh`**: computes its own `BATCH_ID` and
   `BATCH_DIR` (`results/raw/repeated_<batch_id>/`), passes
   `DPEND_RUN_ID=run<i>` / `DPEND_RUN_DIR=$BATCH_DIR/run<i>` into each
   iteration's `run_clean_experiment.sh` call, and writes
   `summary.json` into the batch directory (atomic temp-file+rename,
   same pattern INFRA-001 already used) instead of the fixed
   `/tmp/repeated_<scenario>_summary.json`. A best-effort mirror to that
   old path is kept the same way.

3. **Unified teardown**: added one `teardown_all()` function
   (kill-by-PID first, then the full pattern-based `pkill` sweep --
   launch, gz sim, controller_node.py, lqr_node.py, parameter_bridge,
   robot_state_publisher) and call it from *every* exit path: the
   initial pre-run cleanup, every one of the four pre-flight abort exits,
   and the final success-path cleanup. This directly fixes a real bug
   INFRA-002's own verification run exposed: the pre-flight abort paths'
   pkill lists were missing `parameter_bridge`/`robot_state_publisher`
   (only the success-path cleanup had them), so an aborted LQR run left
   2 orphaned `robot_state_publisher` processes running after the script
   exited. Can't recur now -- there's only one teardown list to maintain.

4. **`ROS_DOMAIN_ID` rotation -- tried, reverted, documented**:
   `NEXT_STEPS.md` explicitly asks for a unique domain id per repeated
   run. Implemented it first (`ROS_DOMAIN_ID=$(( 20 + ($$ % 50) + i ))`
   per iteration), then tested directly before trusting it:

   ```text
   ROS_DOMAIN_ID=0   (default):  /clock available after 5s
   ROS_DOMAIN_ID=149 (rotated):  /clock never available (45s of polling)
   ```

   Confirmed reproducible (re-tested, same result both times). Root
   cause not fully isolated (candidates: `gz_ros2_control`'s internal
   `ros_gz_bridge` spawn path not propagating a non-default domain id
   the way a plain `ros2 run` node would; WSL2's FastRTPS SPDP discovery
   behaving differently on non-default domains) -- not pursued further
   since the practical conclusion is unambiguous either way: rotating
   `ROS_DOMAIN_ID` per run would make every single run `INVALID_INFRA`
   in this project's actual environment, which is the exact opposite of
   what a "run isolation" feature is supposed to achieve. **Reverted.**
   `ROS_DOMAIN_ID` is left unset (default) unless a caller explicitly
   sets one; the environment manifest still records whatever value was
   in effect (`"unknown"` when unset) so this is honestly visible in
   every run's own record, not silently absent.

   This is worth retrying if the project ever moves off this exact
   Ubuntu 22.04 + ROS2 Humble + Gazebo 8.14 "Harmonic" combination --
   see `NEXT_STEPS.md` item 5 (`ENV-001`, Humble+Harmonic vs
   Jazzy+Harmonic comparison), which is a natural place to re-test this.

# Verification (real runs, not synthetic)

Single `pd`/`nominal_balance` run: `run_id=pd_nominal_balance_
20260825T044617Z_6143`, wrote `results/raw/pd_nominal_balance_
20260825T044617Z_6143/{result.json,environment_manifest.json}`. Manifest
content confirmed correct: `ros_distro: humble`, `gazebo_version: Gazebo
Sim, version 8.14.0`, `max_step_size_s: 0.001`, `real_time_factor: 1.0`
(both read live from `empty_world.sdf`, not hardcoded), `ros_domain_id:
unknown` (accurate -- none was set).

`run_repeated_experiment.sh pd nominal_balance 2 0.6`: batch directory
`results/raw/repeated_pd_nominal_balance_20260825T044655Z_6658/` contains
`run1/`, `run2/` (each with its own `result.json` +
`environment_manifest.json`) and a batch-level `summary.json` correctly
aggregating both runs (`n_pass_control=0, n_fail_control=2,
n_invalid_infra=0` -- both real `FAIL_CONTROL` results, no infra flakiness
this time, consistent with CTRL-005/INFRA-002's already-established
baseline).

Process cleanliness after this batch: `ps aux` shows zero leftover
`gz sim`/`parameter_bridge`/`robot_state_publisher`/`controller_node`/
`lqr_node` processes.

# Conclusion

`results/raw/` is now the durable, isolated record of every run and
batch -- nothing is silently overwritten anymore, and every result now
travels with an honest environment manifest. `results/` is `.gitignore`d
(generated data, not source); evidence worth keeping long-term is copied
deliberately into a specific task's `tasks/<TASK-ID>/evidence/`, as this
task's own evidence directory does.

The `ROS_DOMAIN_ID` half of `NEXT_STEPS.md`'s item 3-3 is the one piece
of the plan's literal spec this task does NOT implement, on the basis of
direct, reproducible testing rather than assumption -- documented above
and in both scripts' own comments, not silently dropped.

This completes `NEXT_STEPS.md` item 3 (INFRA-001/002/003) as a whole.
Item 4 (physics-only vs ROS end-to-end mode split) is gated on this item
and remains a separate, not-yet-started task.
