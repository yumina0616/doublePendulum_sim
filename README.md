# Double Pendulum Control (ROS2 + Gazebo)

[English](README.md) | [한국어](README.ko.md)

**Portfolio site**: [bright-muffin-5e2b3e.netlify.app](https://bright-muffin-5e2b3e.netlify.app)
— visualized results and diagrams, same honesty standard as this README (open
problems included, not smoothed over).

A control engineering project that stabilizes a **fully actuated** 2-DOF
double pendulum in the fully inverted (upright) configuration using ROS2
(Humble) + Gazebo Sim (Harmonic) — with an agentic engineering layer on top:
a coding agent that
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
                                  in-memory topic log → Control Metrics
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
| 2 — Classical control | PD, linearization, LQR, initial-condition/disturbance tests | ✅ done — see [limitation](#known-limitation-pd-gain-tuning) below |
| 3 — Automated evaluation harness | Simulation → metrics → `result.json` pass/fail, regression suite | ✅ done — it correctly caught Phase 2's open issue rather than masking it (see limitation below); now splits every run into 4 verdicts (`PASS_CONTROL`/`FAIL_CONTROL`/`INVALID_INFRA`/`FAIL_HARNESS`) instead of a plain pass/fail — see [Experiment validity layer](#experiment-validity-layer) below |
| 4 — Basic coding agent | Task spec → PLAN.md → code change → build → sim → verify | ✅ 5 tasks completed (`CTRL-001`–`CTRL-005`) |
| 5 — Tool architecture | Structured robotics tools vs. raw bash | 🟨 5/6 done (ROS graph inspection, run comparison, etc.); bash-vs-structured-tools ablation deferred |
| 6 — Self-evolving harness | failure store → categorize → propose skill → regression-gated promote/reject | ✅ MVP done — one real skill proposed and evaluated end to end, honestly **REJECTed twice** (N=3, then N=8) — see below |
| 7 — Memory lifecycle / safety | skill retirement, stale-rule detection, approval gate, sandbox policy, red-team scenarios | ✅ MVP done — includes two real vulnerabilities found and fixed against this project's own tooling (`SEC-001`, `SEC-002`) |

Every phase above is backed by a task directory under `tasks/` (spec, plan,
result, evidence) — this isn't a status claim without a paper trail.

## Experiment validity layer

Three follow-on tasks (`INFRA-001`–`003`) made the harness's own
measurements trustworthy enough to build further control work on, plus one
task (`PHYS-001`) that finally answered where this project's run-to-run
variance actually lives:

- **`INFRA-001`** — a plain pass/fail bool used to conflate "the controller
  genuinely failed" with "the experiment never validly ran at all" (zero
  torque, zero samples, a discovery timeout). Every run now gets one of 4
  verdicts (`PASS_CONTROL`/`FAIL_CONTROL`/`INVALID_INFRA`/`FAIL_HARNESS`),
  and `pass_rate` is computed only over the first two — infra/harness
  failure rates are tracked separately instead of silently poisoning the
  control-quality number.
- **`INFRA-002`** — replaced the remaining ad hoc `sleep`s in
  `run_clean_experiment.sh` with explicit polls against real readiness
  signals (`/clock` advancing, `ros2 control list_controllers` reporting
  `active`, publisher+subscriber both connected). Caught a real infra
  failure live during its own verification run — a FastRTPS `/dev/shm`
  accumulation issue `CTRL-005` had already documented as a known factor.
- **`INFRA-003`** — every run/batch now gets an isolated
  `results/raw/<run_id>/` output directory (never overwritten by a later
  run) plus an environment manifest (ROS distro, Gazebo version,
  timestep/solver settings). A planned per-run `ROS_DOMAIN_ID` rotation was
  implemented, tested, and **reverted** after direct measurement showed it
  reliably breaks `/clock` discovery in this project's specific
  WSL2+Gazebo+Humble combination — documented rather than silently kept.
- **`PHYS-001`** — the actual payoff. A new harness drives Gazebo entirely
  through gz-transport (pause/step/wrench/pose — never ROS2/DDS) and
  replays the same disturbance profile open-loop. Result, N=3 independent
  Gazebo relaunches: **bit-for-bit identical trajectories** (max difference
  0.0 rad across 120 samples/run), even under genuinely chaotic,
  uncontrolled dynamics. The *same* scenario run through the existing ROS
  end-to-end path (no controller, so only the DDS/`joint_state_broadcaster`
  layer is added) shows a real, small, nonzero spread instead (`overshoot_q1_deg`
  ranging 223.19°–227.64°, N=3). **The physics solver is deterministic —
  every instance of run-to-run variance this project has observed traces to
  the ROS2/DDS/controller layer, not physics**, confirmed by direct
  measurement rather than inferred from fixing symptoms one at a time.

See `tasks/INFRA-001-verdict-taxonomy/`, `tasks/INFRA-002-readiness-gate/`,
`tasks/INFRA-003-run-isolation/`, and `tasks/PHYS-001-physics-only-harness/`
for the full investigation trail and evidence.

## Known limitation: PD gain tuning

*(This section used to describe an unexplained run-to-run reproducibility
crisis — `CTRL-005` root-caused it; see below.)* Identical PD/LQR runs
against `nominal_balance` used to produce wildly
different outcomes (`CTRL-003` observed `overshoot_q1_deg` of 200.5, 26.8,
63.9 across 3 back-to-back "identical" runs; `CTRL-004`'s statistical
acceptance mode reported 0/5 passing, two of five with essentially zero
torque applied). Two investigations (`CTRL-003`, `CTRL-004`, plus a Phase
6 `N=8` follow-up) failed to isolate why.

**`CTRL-005` found and fixed the actual cause**, and it was not physics or
DDS chaos: two concrete measurement-validity bugs in this project's own
evaluation code. (1) The PD controller's startup path had *no readiness
check at all* (a blind 2-second sleep, unlike LQR's), so the experiment
could start against a controller not yet connected to its command topic —
zero real torque for part of the run. (2) `run_experiment.py`'s recording
schedule started counting down from node *construction* instead of from
real `/joint_states` data arriving, so a slow-enough discovery could burn
through an entire 6-second scenario recording zero samples. Both fixed
with active readiness checks instead of blind waits. Re-verified,
`pd`/`nominal_balance`, N=7 clean runs: `overshoot_q1_deg` now varies by
at most **0.08 degrees** (16.32–16.40) — not 170+. A third, real
contributing factor (stale FastRTPS shared-memory segments from repeated
`pkill -9` cycles) was identified but deliberately left unfixed in the
shared pipeline, since that memory is machine-wide, not project-scoped —
see `tasks/CTRL-005-run-reproducibility/PLAN.md` for why, and the exact
fix for a single-tenant environment.

**What's still open, stated plainly**: none of those 7 clean, reproducible
runs actually *pass* `nominal_balance` — `settling_time_q1_s` consistently
lands at 3.3–3.4s against a 3.0s max. That's no longer a mystery, just an
ordinary, well-posed gain-tuning gap (PD's decentralized law settles
~10–15% too slowly), not yet closed. The pendulum does visibly stabilize
upright — confirmed interactively via the Gazebo GUI for both PD and LQR
during Phase 2 — the open item is clearing the *automated, quantitative*
acceptance threshold consistently, not "does it balance at all." `PHYS-001`
(see [Experiment validity layer](#experiment-validity-layer) above) later
confirmed there's also a separate, small (~4.45°), genuinely real spread
that lives specifically in the ROS2/DDS/controller layer — not further
sub-divided yet (which exact sub-layer contributes it is an open,
well-scoped follow-up), and not the same thing as the gain-tuning gap
above.

`REFACTOR-001` closed a related but distinct risk: the plant's physical
parameters (mass, length, damping, torque limits) and the LQR gain design
used to each hardcode their own independent copy, with nothing enforcing
they stayed in sync. Both now read a single `plant_params.yaml`, and
`lqr_node.py` hard-refuses to start (a specific `STALE GAIN` error, not a
silent wrong-gain run) if that file changes without the cached gain being
regenerated — verified directly, not just designed. The candidate skill
that used to encode this as a rule to remember
(`SKILL-CONTROL-MODEL-CONSISTENCY`, the same one REJECTed twice — see the
opening summary above and `HARNESS-001`) is now formally retired, since
the rule is structurally unnecessary.

See `tasks/CTRL-003-pd-reproducibility/`, `tasks/CTRL-004-statistical-acceptance/`,
`tasks/CTRL-005-run-reproducibility/`, `tasks/PHYS-001-physics-only-harness/`,
and `tasks/REFACTOR-001-plant-single-source/` for the full investigation trail.

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

## Authorship

The coding agent (Claude, via Claude Code) wrote essentially all of the
controller/ROS2/evaluation-harness/agentic-harness implementation code
under a spec-first workflow: for every task, a human-reviewable
`specification.yaml` (goal, allowed/forbidden changes, acceptance criteria)
was fixed *before* the agent implemented anything, so the agent could not
redefine what counted as success after the fact (and see `SEC-001` above
for what mechanically enforces that boundary now). What a human did: set
the project's scope and direction, wrote/approved each task's acceptance
criteria, decided how to interpret ambiguous or borderline results (e.g.
CTRL-003's INCONCLUSIVE verdict, HARNESS-001's REJECT decisions, this
README's own "Known limitation" framing), and reviewed the agent's work at
each step rather than accepting results uncritically — the whole point of
sections like "Known limitation" and the `SEC-001`/`SEC-002` findings is
that convenient-looking results were checked and, in several cases,
rejected or qualified rather than reported as clean wins.

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
  17 tasks completed to date (`CTRL-001`–`005`, `TOOL-001`,
  `BENCH-001`–`003`, `HARNESS-001`, `SEC-001`–`002`, `INFRA-001`–`003`,
  `PHYS-001`, `REFACTOR-001`).
- `harness/failure_store.py` / `categorize_failures.py` / `propose_skill.py`
  — turns failed tasks into a categorized failure store and, once a category
  has enough evidence, a candidate skill YAML (never auto-activated).
- `harness/promote_skill.py` / `retire_skill.py` — the regression gate:
  candidate → active requires a candidate run to *strictly beat* a
  no-skill baseline, **plus a named human approver** (`--approved-by`);
  active skills can be flagged stale (`stale_check.py`, checked against
  real git history) and go through the same gated retirement path.
  Limitation, stated plainly: `--approved-by` records a name, it doesn't
  verify a review happened — nothing currently confirms the named approver
  actually read the procedure before typing it (see `SEC-002` below).
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
    `--approved-by` doesn't have to have read the procedure. Mitigated,
    not solved, with a denylist scan: a keyword match forces a visible
    warning and a *separate* second flag (`--acknowledge-safety-warning`)
    before such a procedure can be trusted. This is a forcing function
    against silently missing the warning, not a real safety proof — a
    reviewer can still type past it without truly understanding the risk,
    and a procedure using none of the denylist's keywords would sail
    through unflagged.

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

# LQR needs a cached gain first (REFACTOR-001) -- one-time, ~1 min:
ros2 run double_pendulum_control design_lqr_gains.py
ros2 run double_pendulum_control lqr_node.py           # loads the cache, starts in ~seconds
# (lqr_node.py refuses to start with a STALE GAIN error if plant_params.yaml
# changed since the cache was last generated -- re-run design_lqr_gains.py,
# or pass -p auto_design:=true to compute inline instead, ~1 min)

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
