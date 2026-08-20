# Double Pendulum Control (ROS2 + Gazebo)

[English](README.md) | [한국어](README.ko.md)

A control engineering project that stabilizes a 2-DOF double pendulum in the
fully inverted (upright) configuration using ROS2 (Humble) + Gazebo Sim
(Harmonic). Classical control (PD, then linearization + LQR) is validated
first, followed by an automated evaluation harness, before an agentic
coding-engineering layer is added on top.

```
Engineering Task → Agent Plan → Code Change → colcon build
                                                     │
                                            Gazebo Simulation
                                                     │
                                  rosbag / topic log → Control Metrics
                                                     │
                                               Pass / Fail
                                                     │
                                Failure Evidence → Skill Candidate
                                                     │
                                    Regression Gate → Promote / Reject
```

**Three layers, one stack:**

```
Agentic Engineering    Planner · Coding Agent · Harness · Skills ·
                        Tool Architecture · Trajectory Memory · Self-Evolution
────────────────────────────────────────────────────────────────────────
Robotics System         ROS2: state_estimator → controller → ros2_control
                        → Gazebo
────────────────────────────────────────────────────────────────────────
Control Engineering     Double pendulum dynamics · linearization · PD/LQR
                        · stability · state feedback · disturbance · saturation
```

A concrete example of what "self-evolving" is supposed to mean here, and
what it isn't: an agent finding better `Kp`/`Q` values is just controller
tuning. What actually counts as harness evolution is the agent learning a
**development habit** — e.g. after repeatedly forgetting to regenerate the
LQR gain whenever the URDF's mass or link length changes, the harness
should propose a rule like *"URDF/Xacro changed → re-linearize → recompute
K → run the regression scenarios"* and only keep that rule active if it
demonstrably reduces that failure across later tasks — not append it
forever, unconditionally, to a growing instructions file (the
"catastrophic remembering" failure mode this design tries to avoid).

This mirrors current (2026) agentic-coding research directions:
regression-gated skill promotion instead of unconditional accumulation,
task plans and results as persistent artifacts (`private/roadmap.md`,
`result.json`) instead of chat context, executable physical feedback — a
real dynamics simulation, not just a test suite — as the evolution signal,
and keeping the agent's write-access architecturally separate from the
real-time control path (see `disturbance.py`'s and `run_experiment.py`'s
docstrings for a concrete case of that boundary mattering in practice).

Phases 0–3 below build the control system and evaluation harness that make
that loop possible. Explaining this project can go three levels deep:
"used ROS2" → "implemented nonlinear double-pendulum dynamics and LQR
stabilization in Gazebo" → "built an automated simulation and
control-performance evaluation harness" → "built a coding agent that uses
that harness to modify controller/ROS2 code and extracts reusable
engineering rules from its own failure trajectories" (Phase 4 onward,
once Phase 3 is solid).

## Current status

- **Phase 0 (environment setup)** — done
- **Phase 1 (plant: URDF/Xacro, Gazebo spawn)** — done
- **Phase 2 (classical control: PD, linearization, LQR)** — done, verified on hardware-in-the-loop simulation
- **Phase 3 (automated evaluation harness)** — in progress (metric computation + automatic `result.json` pass/fail is done; LQR currently fails the `nominal_balance` scenario on joint2 settling time/overshoot and needs re-tuning)
- Phase 4 onward (coding agent, self-evolving skills, etc.) starts once Phase 3 is complete

## Package layout

| Package | Role |
|---|---|
| `double_pendulum_description` | URDF/Xacro model (two uniform rods, fully actuated), Gazebo world, spawn launch file |
| `double_pendulum_control` | PD/LQR controller nodes, linearized plant model, `ros2_control` config |
| `double_pendulum_eval` | Reproducible disturbance tests, metric computation, automated pass/fail runner, scenario definitions |

## Build & run

```bash
source /opt/ros/humble/setup.bash
cd ~/agentic_double_pendulum
colcon build --symlink-install
source install/setup.bash

# 1) Spawn the double pendulum in Gazebo (headless by default: headless:=true)
ros2 launch double_pendulum_description spawn.launch.py headless:=false

# 2) Controller (separate terminal)
ros2 run double_pendulum_control controller_node.py   # PD
ros2 run double_pendulum_control lqr_node.py           # LQR (gain design takes ~1 min)

# 3) Manual disturbance test (separate terminal)
ros2 run double_pendulum_eval disturbance.py --tau1 15.0 --duration 0.3

# 4) Automated evaluation (record + disturb + compute metrics + pass/fail)
ros2 run double_pendulum_eval run_experiment.py --scenario nominal_balance
```

## Requirements

- ROS2 Humble, Gazebo Sim Harmonic (`ros-humble-ros-gzharmonic`)
- `ros-humble-xacro`, `ros-humble-ros2-control`, `ros-humble-ros2-controllers`,
  `ros-humble-joint-state-publisher`
- `gz_ros2_control`: the apt package is built against Gazebo Fortress and
  won't load under Harmonic. Build it from source with `GZ_VERSION=harmonic`
  ([github.com/ros-controls/gz_ros2_control](https://github.com/ros-controls/gz_ros2_control), `humble` branch).
- Python: `scipy` may have an ABI mismatch against numpy 2.x — if so, run
  `pip3 install --user --upgrade scipy`.
