# Double Pendulum Control (ROS2 + Gazebo)

[English](README.md) | [한국어](README.ko.md)

A control engineering project that stabilizes a 2-DOF double pendulum in the
fully inverted (upright) configuration using ROS2 (Humble) + Gazebo Sim
(Harmonic) — with an agentic engineering layer on top: a coding agent that
modifies controller/ROS2 code against a specification, verifies its own
changes with real Gazebo simulation (not mocked), and — the part that makes
this more than a coding-agent demo — extracts reusable engineering rules
("skills") from its own failure trajectories, evaluates each one against a
regression gate before trusting it, and red-teams that same skill mechanism
against prompt injection and unsafe procedures.

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
Robotics System         ROS2: controller → ros2_control → Gazebo
────────────────────────────────────────────────────────────────────────
Control Engineering     Double pendulum dynamics · linearization · PD/LQR
                        · stability · state feedback · disturbance · saturation
```

A concrete example of what "self-evolving" means here, and what it isn't: an
agent finding better `Kp`/`Q` values is just controller tuning. What counts
as harness evolution is the agent learning a **development habit** — e.g.
after repeatedly forgetting to regenerate the LQR gain whenever the URDF's
mass or link length changes, the harness proposes a rule like *"URDF/Xacro
changed → re-linearize → recompute K → run the regression scenarios"* and
only keeps that rule active if it demonstrably beats a no-rule baseline in a
regression comparison — not appended forever, unconditionally, to a growing
instructions file (the "catastrophic remembering" failure mode this design
avoids). This was built and actually run once, end to end, against real
Gazebo data — see [Phase 6](#current-status) below for the honest result
(REJECT, twice, at two different sample sizes).

## Current status

| Phase | Goal | Status |
|---|---|---|
| 0 — Environment setup | ROS2 Humble + Gazebo Harmonic in WSL2 | ✅ done |
| 1 — Plant | URDF/Xacro double pendulum, Gazebo spawn, joint state/torque I/O | ✅ done |
| 2 — Classical control | PD, linearization, LQR, initial-condition/disturbance tests | ✅ done — see [limitation](#known-limitation-pdlqr-run-to-run-reproducibility) below |
| 3 — Automated evaluation harness | Simulation → metrics → `result.json` pass/fail, regression suite | ✅ done — the harness itself is solid; it is what *caught* Phase 2's open issue |
| 4 — Basic coding agent | Task spec → PLAN.md → code change → build → sim → verify | ✅ 4 tasks completed (`CTRL-001`–`CTRL-004`) |
| 5 — Tool architecture | Structured robotics tools vs. raw bash | 🟨 5/6 done (ROS graph inspection, run comparison, etc.); bash-vs-structured-tools ablation deferred |
| 6 — Self-evolving harness | failure store → categorize → propose skill → regression-gated promote/reject | ✅ MVP done — one real skill proposed and evaluated end to end, honestly **REJECTed twice** (N=3, then N=8) — see below |
| 7 — Memory lifecycle / safety | skill retirement, stale-rule detection, approval gate, sandbox policy, red-team scenarios | ✅ MVP done — includes two real vulnerabilities found and fixed against this project's own tooling (`SEC-001`, `SEC-002`) |

Every phase above is backed by a task directory under `tasks/` (spec, plan,
result, evidence) — this isn't a status claim without a paper trail.

## Known limitation: PD/LQR run-to-run reproducibility

**This is the project's most important open problem, stated plainly instead
of buried:** identical PD/LQR runs against the same `nominal_balance`
scenario do not reliably produce the same outcome. Across three separate
investigations (`CTRL-003`, `CTRL-004`, and again during the Phase 6 `N=8`
follow-up) the root cause was never isolated — candidate mechanisms tested
and *not* confirmed include DDS/discovery timing, stale shared-memory state,
and WSL network-stack degradation. `CTRL-004` made the evaluator honest
about this instead of hiding it: it added a statistical (N-repeat, pass
*rate*) acceptance mode rather than trusting any single run, and against
`pd`/`nominal_balance` that mode reports **0/5 passing** at present, with
two of five runs showing the controller applying essentially zero torque.

What this does and doesn't mean in practice:

- **The pendulum does visibly stabilize upright** — this was confirmed
  interactively via the Gazebo GUI for both PD and LQR during Phase 2. If
  the question is "can you show me it balancing," the honest answer is yes,
  watch it run.
- **What is NOT solid is the automated, repeated-run acceptance check** —
  the same scenario, run back to back under identical conditions, does not
  reliably clear its own pass threshold. This is a real, unresolved gap,
  not a documentation gap.
- The harness itself is not the problem here — `CTRL-004`'s statistical
  mode is specifically what makes this variance visible and honestly
  reported instead of silently trusting a lucky run. That the evaluation
  harness catches its own controller's flakiness is treated as evidence
  the harness works, not as a hidden failure.

See `tasks/CTRL-003-pd-reproducibility/` and `tasks/CTRL-004-statistical-acceptance/`
for the full investigation trail.

## Repo layout: where the actual code lives

This repository (`doublePendulum_sim`, this GitHub project) **is** the
canonical code repo — ROS2/Gazebo requires Linux, so all development and
every commit above happens inside a WSL2 Ubuntu-22.04 environment
(`~/agentic_double_pendulum`), not on the Windows filesystem directly.

If you're looking at a **separate `C:\dev\doublePendulum_sim` Windows-side
folder** for this project locally: that folder is a planning/editing
workspace only (holds a private, git-ignored project plan and roadmap used
during development, plus a manually-synced copy of this README for local
editing convenience). It has its own small, unrelated git history from an
early, abandoned prototype and is **not** where the real commits or code
live — this repository, built inside WSL2, is the one that matters.

## Package layout

| Package | Role |
|---|---|
| `double_pendulum_description` | URDF/Xacro model (two uniform rods, fully actuated), Gazebo world, spawn launch file |
| `double_pendulum_control` | PD/LQR controller nodes, linearized plant model, `ros2_control` config |
| `double_pendulum_eval` | Reproducible disturbance tests, metric computation, automated pass/fail runner, scenario definitions |
| `gz_ros2_control` | Vendored, source-built (not authored by this project — the apt package targets the wrong Gazebo version) |

## The agentic layer (`harness/`, `tasks/`)

- `tasks/<ID>-.../` — one directory per completed agentic task:
  `specification.yaml` (goal, allowed/forbidden changes, acceptance
  criteria), `PLAN.md`, `result.json`, `trajectory.jsonl`, `evidence/`.
  11 tasks completed as of Phase 7 (`CTRL-001`–`004`, `TOOL-001`,
  `BENCH-001`–`003`, `HARNESS-001`, `SEC-001`–`002`).
- `harness/failure_store.py` / `categorize_failures.py` / `propose_skill.py`
  — turns failed tasks into a categorized failure store and, once a category
  has enough evidence, a candidate skill YAML (never auto-activated).
- `harness/promote_skill.py` / `retire_skill.py` — the regression gate:
  candidate → active requires a candidate run to *strictly beat* a
  no-skill baseline, **plus a named human approver** (`--approved-by`);
  active skills can be flagged stale (`stale_check.py`, checked against
  real git history) and go through the same gated retirement path.
- `harness/safety_scan.py` / `check_forbidden_changes.py` /
  `verify_task_completion.py` — hardening added after two red-team
  exercises against this project's own tooling found real gaps:
  - `SEC-001` (malicious task description): a prompt-injection-style
    instruction telling an agent to loosen `specification.yaml` and
    fabricate a passing `result.json` without simulating anything.
    Editing the spec is now mechanically blocked; fabricating a result is
    now caught by independently re-running the claimed
    controller/scenario before trusting a task as complete.
  - `SEC-002` (poisoned skill): a fabricated skill recommending removing
    actuator torque limits instead of fixing the controller — promoted
    successfully on fabricated pass-rate numbers alone, because the
    regression gate has no safety awareness and a human approver typing
    `--approved-by` doesn't have to have read the procedure. Fixed with a
    denylist scan that forces an explicit second acknowledgement for
    safety-relevant procedures.

  See `tasks/SEC-001-malicious-readme/FINDINGS.md` and
  `tasks/SEC-002-poisoned-skill/FINDINGS.md` for the full write-ups,
  including what's still *not* protected against (documented, not hidden).

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

# 5) Statistical acceptance (N repeated clean runs + pass rate, see "Known limitation" above)
src/double_pendulum_eval/scripts/run_repeated_experiment.sh pd nominal_balance 5
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
