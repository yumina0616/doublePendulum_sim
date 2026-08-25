# Goal

Per `private/NEXT_STEPS.md` item 6: `double_pendulum.urdf.xacro`'s
`xacro:property` block and `linear_model.py`'s `PendulumParams` dataclass
each hardcoded their own independent copy of the same physical constants
(m1=m2=L1=L2=1.0, damping=0.05, tau1_max=60/tau2_max=30). Nothing
mechanically enforced they stayed in sync -- exactly the background
`SKILL-CONTROL-MODEL-CONSISTENCY` (a REJECTed candidate, never promoted
to `active`) was written to guard against as a *remembered procedure*.
Make one file the truth both sides read, and turn "forgot to
regenerate the gain after changing the plant" into a loud runtime
failure instead of a silent wrong-gain run.

# Investigation: how xacro can read an external YAML

Checked whether xacro has a native mechanism before writing a custom
code-generation step. `xacro/__init__.py` exposes `load_yaml()` directly
into `${}` expression scope (as `xacro.load_yaml(...)`, confirmed by
reading the ROS2 Humble xacro package source at
`/opt/ros/humble/local/lib/python3.10/dist-packages/xacro/__init__.py`).
Path resolution (`abs_filename_spec`) is relative to the *currently
processed file's own directory* if not absolute -- so
`xacro.load_yaml('../config/plant_params.yaml')` from
`urdf/double_pendulum.urdf.xacro` resolves correctly without needing
`$(find pkg)` substitution (which, it turns out, doesn't work nested
inside a `${}` Python-eval block anyway -- tried it first, got an XML
parse error, switched to a relative path instead).

Two real bugs hit and fixed during this step, both confirmed by directly
running `xacro` standalone rather than assuming it would work:
1. `$(find double_pendulum_description)` nested inside `${xacro.load_yaml(...)}`
   broke XML parsing (column-accurate error at the exact `$(` token) --
   switched to a path relative to the xacro file's own directory instead.
2. XML comments cannot contain a literal `--` anywhere in their text
   (the XML spec forbids it) -- my own explanatory comment above the new
   property block had "plant_params.yaml -- also read", which broke
   parsing at that exact character. Fixed by rewording.

# Implementation

1. **`plant_params.yaml`** (new, `double_pendulum_description/config/`):
   the single source -- same numeric values the old hardcoded copies
   had, nothing changed physically.
2. **`double_pendulum.urdf.xacro`**: the old 10-line hardcoded
   `xacro:property` block replaced with `xacro.load_yaml(...)` plus one
   property-per-key referencing the loaded dict. Verified: `xacro
   double_pendulum.urdf.xacro` processes cleanly and the generated URDF's
   `mass`/`effort`/`damping` values match plant_params.yaml exactly.
3. **`plant_params.py`** (new, `double_pendulum_control/`): shared
   `load_plant_params()` (local-source-first, matching
   `run_experiment.py`'s `find_scenario_path` convention -- works with
   `--symlink-install` without a rebuild) and `plant_hash()` (SHA-256
   over a canonicalized/sorted JSON dump, so key order and float repr
   don't affect the hash).
4. **`linear_model.py`**: `PendulumParams` lost its hardcoded numeric
   defaults entirely (now required fields) -- added `from_plant_dict()`
   and `load()` classmethods. `DoublePendulum.__init__`'s no-args path
   now calls `PendulumParams.load()`, which raises loudly if
   `plant_params.yaml` can't be found, rather than silently falling back
   to numbers that could drift from the real single source. Verified:
   `python3 linear_model.py` self-test still reproduces the same A/B
   matrices and controllability result as before.
5. **`lqr_controller.py`**: `design_lqr()` now sources `tau1_max`/
   `tau2_max` from `plant_params.yaml` when building the returned
   `LQRGains` -- previously `LQRGains`'s own dataclass defaults
   (60.0/30.0) were used unconditionally and never actually checked
   against anything (a silent third copy of these numbers that happened
   to match by coincidence, not by reference).
6. **`design_lqr_gains.py`** (new): precomputes the LQR gain (same
   `design_lqr()` call the old inline path used) and saves
   `{plant_hash, q_diag, r_diag, K, tau1_max, tau2_max, computed_at}` to
   `lqr_gain_cache.json` (atomic write, same temp-file+rename pattern
   INFRA-001/003 already use elsewhere in this project).
7. **`lqr_node.py`**: no longer computes the gain inline by default.
   `load_cached_gains()` loads the cache and requires an exact match on
   `plant_hash` AND `q_diag`/`r_diag` (so changing *either* the plant
   *or* the requested Q/R weights without regenerating the cache is
   caught, not just plant drift) -- raises `RuntimeError` with a specific
   reason (no cache / stale plant / mismatched weights) if not. On
   mismatch, the node refuses to start (`SystemExit`) unless
   `-p auto_design:=true` is passed, which falls back to the old
   compute-inline-every-time behavior with a loud warning logged first.
   The "LQR ready" log line `run_clean_experiment.sh` already greps for
   (its readiness-gate check) now prints unconditionally after full node
   setup (subscription/publisher/timer all created) rather than right
   after gain design -- a strictly safer position than before, not a
   regression (INFRA-002 already added a separate, stronger pub+sub
   connectivity check on top of this log-line check, so timing here was
   never load-bearing on its own).
8. **`SKILL-CONTROL-MODEL-CONSISTENCY`**: moved from
   `harness/skills/candidates/` to a new `harness/skills/retired/`
   (didn't exist before this task) with `status: retired` and a
   `retirement_reason` field explaining why -- this candidate was never
   promoted to `active` (REJECTed by its own `HARNESS-001` evaluation),
   so this is a direct status update rather than going through
   `retire_skill.py`'s active-skill retirement-eval flow (which exists
   for a *currently active, currently trusted* skill being re-evaluated
   -- doesn't apply here, since this skill was never trusted in the
   first place).

# Verification (real runs, not synthetic)

**xacro processing**: `xacro double_pendulum.urdf.xacro` exits 0;
generated URDF's `mass value="1.0"` (x3), `effort="60.0"`/`"30.0"`,
`damping="0.05"` (x2) all match `plant_params.yaml` exactly.

**Cache-hit path**: `design_lqr_gains.py` run once (18.4s, plant_hash
`564ef19e89ea8c2b`), then `ros2 run double_pendulum_control lqr_node.py`
loads the cache and logs `"Loaded cached LQR gain (skipped CARE solve)"`
with the identical K matrix `lqr_controller.py`'s own self-test computed
directly -- confirms the cached values are exactly what a fresh
computation from the same plant params would produce, not a stale
artifact.

**Stale-gain rejection (the core acceptance criterion)**: edited
`plant_params.yaml`'s `m1: 1.0 -> 1.5` *without* regenerating the cache.
`lqr_node.py` immediately logged:

```text
STALE GAIN: plant_params.yaml has changed since this gain was designed
(cached plant_hash=564ef19e89ea8c2b, current plant_hash=e4a96a3ff595164d).
Re-run design_lqr_gains.py, or pass -p auto_design:=true to compute
inline instead (~1 min).
```

and exited 1 -- did not start, did not silently run against the old
gain. Restored `m1` to `1.0`, regenerated the cache, confirmed normal
startup resumed.

**`auto_design:=true` escape hatch**: confirmed it proceeds past the
mismatch (computes a fresh gain inline instead of refusing) rather than
being dead code -- verified by observing it reach `create_subscription`
(past the design_lqr call) in an interrupted test run.

**Full Gazebo integration, both controllers** (`run_clean_experiment.sh`,
real runs, not synthetic): `lqr`/`nominal_balance` reached `[4/4]` with
`"LQR ready (after 3s)"` (previously ~54s per INFRA-002's own evidence --
skipping the CARE solve is a large practical speedup, not just a
correctness fix) and produced a genuine `FAIL_CONTROL` result consistent
with the project's already-documented LQR gain-quality gap. `pd`/
`nominal_balance` also reached `[4/4]` with a genuine `FAIL_CONTROL`
result in the same range as prior runs -- neither path regressed.

# Conclusion

`plant_params.yaml` is now the only place these physical constants are
written down; both the simulated plant (via xacro) and the LQR gain
design (via Python) read it directly, so the two can no longer
independently drift the way `SKILL-CONTROL-MODEL-CONSISTENCY` was
written to catch by convention. The gain cache turns "forgot to
regenerate after a plant change" into an immediate, specific, loud
failure -- verified directly, not just designed and assumed to work.
As a side effect, `lqr_node.py` startup dropped from ~54s (fresh CARE
solve every time) to ~3s (cache hit) in the common case.

`SKILL-CONTROL-MODEL-CONSISTENCY` is retired with its reasoning recorded
in the YAML, per `NEXT_STEPS.md`'s explicit completion condition for
this item.

This completes `NEXT_STEPS.md` items 3, 4, and 6 (INFRA-001/002/003,
PHYS-001, REFACTOR-001). Item 5 (`ENV-001`, distro comparison) remains a
separate, not-yet-started task; item 7 (RecurDyn) stays gated until item
5 is also done, per the plan's own scoping.
