# Skill lifecycle, sandboxing, and approval (Phase 7)

Extends the Phase 6 harness (`propose_skill.py` / `promote_skill.py`) with
the rest of project_plan.md section 13's state machine and section 16's
safety principles.

## State machine

```
candidate -> active -> candidate_for_retirement -> retirement_eval -> retired | active
```

| transition | script | gated by |
|---|---|---|
| candidate -> active | `promote_skill.py` | regression comparison (candidate pass_rate > baseline pass_rate) + `--approved-by` |
| active -> candidate_for_retirement | `retire_skill.py flag` | none (a proposal only, like evidence-gathering) |
| candidate_for_retirement -> retirement_eval -> retired/active | `retire_skill.py eval` | same regression comparison, re-run fresh + `--approved-by` |

`retire_skill.py flag` is normally driven by `stale_check.py`'s output, but
takes `--reason` directly so it isn't the only way to open a review.

## Stale rule detection (`stale_check.py`)

Scans `skills/active/*.yaml` and flags a skill for retirement review if
either:

1. `negative_regression_count > 0` -- the skill has already caused a
   measured regression since activation, or
2. a file matching the skill's own `trigger.changed_files` glob was
   touched by a git commit **after** the skill's `last_verified_date` --
   i.e. the exact kind of change the skill's evidence was built on has
   happened again since, without the skill being re-verified against it.

Rule 2 is mechanically checked against real git history (`git log -1
--format=%cI -- <pattern>`), not a manually-maintained staleness counter.
Flagging never retires anything by itself -- it only proposes the
`active -> candidate_for_retirement` transition; the actual keep/retire
decision still goes through `retire_skill.py eval`.

## Approval gate

Per section 16 ("Approval" gate before "Accepted Branch"), the only two
transitions that mutate `skills/active/` -- promoting a candidate in, and
finalizing a retirement decision -- both require `--approved-by <name>`
and refuse (non-zero exit) without it. Proposing a candidate
(`propose_skill.py`) and flagging one for retirement review
(`retire_skill.py flag`) do not require approval, since neither changes
what's actually active -- they only queue something for a gated decision.

`--approved-by` alone is a *procedural* gate (someone must type a name),
not a *substantive* one -- see `tasks/SEC-002-poisoned-skill/FINDINGS.md`,
which demonstrated a real promotion of an unsafe skill on nothing but a
good pass_rate number. `harness/safety_scan.py` adds a second layer: if
the candidate/active skill's `procedure` text matches a denylist of
safety-relevant keywords, both `promote_skill.py` and `retire_skill.py
eval` additionally require `--acknowledge-safety-warning` before writing
PROMOTE or STAY_ACTIVE. Not a hard block (a match isn't proof of an unsafe
skill) -- a forcing function so a reviewer can no longer approve without
at least being shown the warning.

## Sandbox policy

A skill's `procedure` field is declarative text only. Checked directly:
no script in `harness/` or `src/` ever parses or executes a skill's
`procedure` list (`grep -rn procedure harness/ src/` turns up only the
schema/comment references in `propose_skill.py`/`promote_skill.py`, never
an `exec`/`eval`/`subprocess` call driven by skill content). A skill can
only affect the codebase through a human or agent reading its `procedure`
steps and manually carrying them out as an ordinary task -- the same path
as any other engineering judgment call -- which is then evaluated exactly
like any other change: build check, Gazebo simulation, regression suite
(see section 16's gate list). There is no code path where accepting a
skill (or a poisoned one, see below) results in unreviewed code execution.

## Lifecycle self-test (2026-08-23)

`skill_yaml.py`'s `set_field`/`get_field`/`get_list_field` were checked
read-only against the real `SKILL-CONTROL-MODEL-CONSISTENCY.yaml` (parses
id/status/trigger/evidence correctly; a `status` overwrite leaves exactly
one `status:` line, not a duplicate -- the bug an earlier draft of
`retire_skill.py` had before this rewrite).

The full state machine was then run end-to-end against **synthetic
fixture skills** (`SKILL-TEST-LIFECYCLE-DEMO`, `-DEMO2`, deleted after the
run -- not evidence-backed, not committed):

- `stale_check.py` correctly flagged a fixture whose trigger pattern
  (`*.xacro`) matched a real commit (2026-08-20) after the fixture's
  `last_verified_date` (2026-08-19).
- `retire_skill.py flag` moved it `active -> candidate_for_retirement`.
- `retire_skill.py eval` without `--approved-by` was refused (argparse
  `required=True`).
- With `--approved-by`, a worse-than-baseline candidate summary produced
  `RETIRE` and moved the file to `skills/retired/`.
- A second fixture, same flag step, but a still-better-than-baseline
  candidate summary produced `STAY_ACTIVE` and refreshed
  `last_verified_date` to today -- confirmed by re-running `stale_check.py`
  afterward and seeing the flag clear.

No real skill file was touched by this test. `skills/active/` and
`skills/retired/` are both empty afterward (the one real skill,
`SKILL-CONTROL-MODEL-CONSISTENCY`, remains `candidate`/REJECTed in
`skills/candidates/`, per HARNESS-001 and its N=8 follow-up -- retirement
has nothing real to act on yet since nothing has been promoted).
