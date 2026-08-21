#!/usr/bin/env python3
"""Phase 6, step 2: failure categorization.

Groups failure_store.jsonl records by a simple, explainable rule (matching
project_plan.md section 11.1's worked example): a task that touched a
plant-definition file (*.xacro / *.urdf / *model_params*) but did NOT also
touch a controller-model file (linear_model.py / lqr_controller.py /
pd_controller.py) in the same task is categorized as
"plant-model-inconsistency" -- the plant changed but the controller's
internal model of the plant didn't.

Deliberately rule-based, not ML-based: the point of this phase is an
auditable, explainable pipeline, not a black-box classifier.

    python3 categorize_failures.py [--in failure_store.jsonl] [--out failure_categories.json]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PLANT_FILE_PATTERNS = [r"\.xacro", r"\.urdf", r"model_params"]
CONTROLLER_MODEL_FILE_PATTERNS = [r"linear_model\.py", r"lqr_controller\.py", r"pd_controller\.py"]


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def categorize(records: list[dict]) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}
    for r in records:
        changes = " ".join(r.get("allowed_changes", []))
        touched_plant = _matches_any(changes, PLANT_FILE_PATTERNS)
        touched_controller_model = _matches_any(changes, CONTROLLER_MODEL_FILE_PATTERNS)
        if touched_plant and not touched_controller_model:
            categories.setdefault("plant-model-inconsistency", []).append(r["task_id"])
        # future categories would be added here as new rules, following the
        # same explicit if/append pattern -- not meant to be exhaustive yet
    return categories


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default=str(Path(__file__).resolve().parent / "failure_store.jsonl"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "failure_categories.json"))
    args = ap.parse_args()

    records = [json.loads(line) for line in Path(args.in_path).read_text().splitlines() if line.strip()]
    categories = categorize(records)

    Path(args.out).write_text(json.dumps(categories, indent=2) + "\n")
    print(f"Categorized {len(records)} failure record(s) into {len(categories)} categor(y/ies):")
    for cat, task_ids in categories.items():
        print(f"  - {cat}: {task_ids} ({len(task_ids)} evidence)")


if __name__ == "__main__":
    main()
