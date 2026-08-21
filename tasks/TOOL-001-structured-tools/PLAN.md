# Goal

Fill in the two missing Phase 5 checklist items: a ROS graph inspection
tool and a run comparison tool.

# Observed baseline

Phase 5's checklist (project_plan.md section 10.2 example):
`inspect_ros_graph()`, `run_control_experiment()`, `calculate_control_metrics()`,
`inject_disturbance()`, `compare_runs()`. We already have equivalents for
4 of 5 (experiment runner, metric tool, disturbance injection, and
`run_regression_suite.sh` covers batch running but not a focused
"compare run A vs run B" diff). Nothing exists yet for ROS graph
introspection.

# Proposed work

1. `inspect_ros_graph.py`: shells out to `ros2 node list` and
   `ros2 topic list`, then `ros2 topic info -v <topic>` for each topic to
   get publisher/subscriber counts and types, assembles it into one JSON
   object `{nodes: [...], topics: {name: {type, publishers, subscribers}}}`.
2. `compare_runs.py`: takes two paths to `result.json` files (as produced
   by `run_experiment.py`), loads both, and for every key under `metrics`
   prints old value, new value, and delta; also reports if `passed`
   flipped. Exit code 0 always (it's a reporting tool, not a pass/fail
   gate itself).
3. Verify `inspect_ros_graph.py` against a live Gazebo+PD session (agent
   self-executes, per the CTRL-003 capability finding).
4. Verify `compare_runs.py` against two real result.json files already on
   disk from earlier CTRL-003 runs (known to differ) to confirm it
   reports a sensible diff.

# Acceptance Criteria

See specification.yaml.
