# Goal

Fix the joint_state_broadcaster / effort_controller spawn race in
`spawn.launch.py`.

# Observed baseline

While repeating `run_clean_experiment.sh pd impulse_disturbance` to check
whether PD's wildly varying results were a harness bug, one run failed
during controller loading (not during the experiment itself):

```
[spawner-5] [WARN] ... Failed getting a result from calling
  /controller_manager/configure_controller in 10.0. (Attempt 1 of 3.)
... (x3)
[spawner-5] RuntimeError: Could not successfully call service
  /controller_manager/configure_controller after 3 attempts.
[ERROR] [spawner-5]: process has died [pid 27062, exit code 1, ...]
```

`effort_controller` configured/activated successfully around the same
time. Root cause: `spawn.launch.py`'s `RegisterEventHandler(OnProcessExit(
target_action=spawn_entity, on_exit=[joint_state_broadcaster_spawner,
effort_controller_spawner]))` starts *both* spawner processes at once --
they race two concurrent `configure_controller` calls against the same
`controller_manager`, and joint_state_broadcaster's can time out.

# Proposed work

1. Split the single `OnProcessExit` handler into two chained ones:
   `spawn_entity` exit -> load `joint_state_broadcaster` -> (its exit) ->
   load `effort_controller`.
2. Verify by running `run_clean_experiment.sh pd nominal_balance`
   repeatedly and confirming no configure_controller timeout/crash appears
   in any run.

# Acceptance Criteria

- controllers load sequentially (code review of the launch file)
- 2+ repeated real-Gazebo runs complete controller loading without error

# Note (explicitly out of scope for this task)

The underlying PD physics results remained highly variable run-to-run
*even after* this fix (overshoot 200.5 deg vs 26.8 deg across two
otherwise-identical clean runs) -- so the spawn race was a real, separate
bug, but not the (or not the only) cause of PD's non-reproducibility.
That's tracked as a distinct open question in private/roadmap.md, not
addressed here.
