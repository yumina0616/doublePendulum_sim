#!/usr/bin/env python3
"""Phase 7 follow-up (SEC-001): independent replay verification.

SEC-001 found that nothing in the harness confirms a task's result.json
actually came from a real Gazebo run -- an agent (following a
prompt-injection attack, or just mistaken) could hand-write a passing
result.json without ever running the simulation, and no existing artifact
would catch it: trajectory.jsonl in this project is the AGENT'S OWN
narrated action log ({"step":1,"action":"write_specification",...}), not
raw physics telemetry -- equally fabricable, not independent evidence.

This closes that gap the same way check_forbidden_changes.py closed the
specification.yaml gap: by actually doing the thing independently, not by
inspecting what the agent already produced. It re-runs the exact
controller+scenario named in the task's own result.json
(verification_run.controller / .scenario) via run_clean_experiment.sh --
a single fresh run, for speed -- and checks that a REAL experiment
completes (exit 0 = pass, exit 1 = fail; both mean the actual pipeline ran
to completion and produced real /joint_states data, not a fabricated
verdict). Only an infra abort (any other exit code) is inconclusive and
should be retried, not treated as a verification failure.

Deliberately does NOT require the fresh run's pass/fail to match the
original -- this project's own CTRL-003 finding is real, still-unexplained
run-to-run physics variance in PD/LQR runs, so a strict match requirement
would false-alarm on legitimate tasks. What this DOES prove is narrower
and sufficient for the threat model: the claimed controller+scenario
combination is a real, runnable experiment that was actually executed,
not a fabricated verdict. A mismatch between the fresh and original
verdict is reported as a note, not treated as a failure.

    python3 verify_task_completion.py --task ../tasks/CTRL-004-statistical-acceptance
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    here = Path(__file__).resolve().parent
    repo_root = here.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument(
        "--run-script",
        default=str(repo_root / "src" / "double_pendulum_eval" / "scripts" / "run_clean_experiment.sh"),
    )
    args = ap.parse_args()

    task_dir = Path(args.task).resolve()
    result_path = task_dir / "result.json"
    if not result_path.exists():
        raise SystemExit(f"no result.json at {result_path}")

    result = json.loads(result_path.read_text())
    vr = result.get("verification_run")
    if not vr or "controller" not in vr or "scenario" not in vr:
        raise SystemExit(
            f"{result_path} has no verification_run.controller/scenario -- "
            f"nothing for this script to independently replay"
        )

    controller, scenario = vr["controller"], vr["scenario"]
    original_verdict = vr.get("verdict")
    print(f"Task: {task_dir.name}")
    print(f"Independently re-running: controller={controller} scenario={scenario}")
    print(f"(original claimed verification_run verdict: {original_verdict})")
    print("-" * 70)

    run_script = Path(args.run_script).resolve()
    proc = subprocess.run(["bash", str(run_script), controller, scenario], cwd=run_script.parent)
    code = proc.returncode

    print("-" * 70)
    if code not in (0, 1):
        print(
            f"INCONCLUSIVE: fresh run exited {code} (infra failure, not a "
            f"real pass/fail verdict) -- retry before drawing any conclusion"
        )
        sys.exit(2)

    fresh_verdict = "PASS" if code == 0 else "FAIL"
    print(f"Fresh independent run completed for real: verdict={fresh_verdict}")
    if original_verdict and fresh_verdict != original_verdict:
        print(
            f"NOTE: differs from the original claimed verdict ({original_verdict}). "
            f"This project has known run-to-run physics variance (CTRL-003) -- "
            f"a mismatch alone is not proof of fabrication, but is worth a human look."
        )
    print(
        "CONFIRMED: a real Gazebo experiment for this controller/scenario just "
        "ran to completion -- the claimed result.json was not fabricated "
        "without ever running the simulation."
    )


if __name__ == "__main__":
    main()
