#!/usr/bin/env python3
"""Phase 6, step 3: skill proposal.

For any failure category with enough evidence (default: >=2 tasks), emit a
candidate skill YAML under harness/skills/candidates/, in the schema from
project_plan.md section 11.1 (id/trigger/procedure/reason/evidence) plus
the lifecycle metadata fields from section 13 (status/created_from/
created_at/activation_count/etc), initialized as "candidate" -- a proposed
skill is NEVER auto-activated. Promotion is a separate, explicit step
(promote_skill.py) gated on a regression comparison.

    python3 propose_skill.py [--in failure_categories.json] [--min-evidence 2]
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

# One template per known category. Deliberately hand-authored (not
# auto-generated from the failure text) -- the *evidence* is automatic,
# the engineering judgment about *what procedure fixes it* is not, per
# project_plan.md's own framing of skills as reviewed knowledge assets.
SKILL_TEMPLATES = {
    "plant-model-inconsistency": {
        "id": "SKILL-CONTROL-MODEL-CONSISTENCY",
        "trigger": {
            "changed_files": ["*.urdf", "*.xacro", "*model_params*"],
        },
        "procedure": [
            "detect plant parameter change",
            "regenerate linear model (linear_model.py's PendulumParams)",
            "recompute controller gain (lqr_controller.py design_lqr)",
            "run nominal simulation",
            "run regression evaluation",
        ],
        "reason": "Controller matrices (LQR K, PD gains if re-tuned) depend "
                   "on the plant's mass/length parameters through the "
                   "linearized model. Changing the plant definition without "
                   "regenerating that model leaves the controller acting on "
                   "a stale, now-incorrect physical model.",
    }
}


def propose(categories: dict, min_evidence: int, out_dir: Path) -> list[Path]:
    written = []
    for category, task_ids in categories.items():
        if len(task_ids) < min_evidence:
            print(f"skip '{category}': only {len(task_ids)} evidence (< {min_evidence})")
            continue
        template = SKILL_TEMPLATES.get(category)
        if template is None:
            print(f"skip '{category}': no known skill template for this category yet")
            continue

        skill = {
            "id": template["id"],
            "trigger": template["trigger"],
            "procedure": template["procedure"],
            "reason": template["reason"],
            "evidence": task_ids,
            # lifecycle metadata, project_plan.md section 13
            "status": "candidate",
            "created_from": task_ids,
            "created_at": datetime.date.today().isoformat(),
            "last_verified": None,
            "activation_count": 0,
            "success_after_activation": 0,
            "negative_regression_count": 0,
        }

        out_path = out_dir / f"{template['id']}.yaml"
        _write_yaml(skill, out_path)
        written.append(out_path)
        print(f"proposed candidate skill: {out_path} (evidence: {task_ids})")
    return written


def _write_yaml(data: dict, path: Path):
    # hand-rolled YAML emission (avoids a hard PyYAML dependency, and the
    # schema is simple/flat enough not to need a real serializer)
    lines = [f"id: {data['id']}", "", "trigger:"]
    for k, v in data["trigger"].items():
        lines.append(f"  {k}:")
        for item in v:
            lines.append(f"    - \"{item}\"")
    lines += ["", "procedure:"]
    for step in data["procedure"]:
        lines.append(f"  - {step}")
    lines += ["", f"reason: >", f"  {data['reason']}", "", "evidence:"]
    for e in data["evidence"]:
        lines.append(f"  - {e}")
    lines += [
        "",
        f"status: {data['status']}",
        "created_from:",
    ]
    for e in data["created_from"]:
        lines.append(f"  - {e}")
    lines += [
        f"created_at: {data['created_at']}",
        f"last_verified: {data['last_verified']}",
        f"activation_count: {data['activation_count']}",
        f"success_after_activation: {data['success_after_activation']}",
        f"negative_regression_count: {data['negative_regression_count']}",
    ]
    path.write_text("\n".join(lines) + "\n")


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default=str(here / "failure_categories.json"))
    ap.add_argument("--min-evidence", type=int, default=2)
    ap.add_argument("--out-dir", default=str(here / "skills" / "candidates"))
    args = ap.parse_args()

    categories = json.loads(Path(args.in_path).read_text())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    propose(categories, args.min_evidence, out_dir)


if __name__ == "__main__":
    main()
