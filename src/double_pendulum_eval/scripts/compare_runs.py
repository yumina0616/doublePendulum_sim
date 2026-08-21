#!/usr/bin/env python3
"""Phase 5 (Tool Architecture): run comparison tool.

Structured diff between two result.json files (as produced by
run_experiment.py), instead of eyeballing two JSON blobs side by side.

    python3 compare_runs.py /tmp/run_a_result.json /tmp/run_b_result.json
    python3 compare_runs.py --pretty a.json b.json
"""
import argparse
import json


def load(path):
    with open(path) as f:
        return json.load(f)


def compare(a: dict, b: dict) -> dict:
    metrics_a = a.get("metrics", {})
    metrics_b = b.get("metrics", {})
    keys = sorted(set(metrics_a) | set(metrics_b))

    deltas = {}
    for k in keys:
        va, vb = metrics_a.get(k), metrics_b.get(k)
        delta = None
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            try:
                delta = vb - va
            except (TypeError, OverflowError):
                delta = None
        deltas[k] = {"a": va, "b": vb, "delta": delta}

    return {
        "scenario_a": a.get("scenario"),
        "scenario_b": b.get("scenario"),
        "controller_a": a.get("controller"),
        "controller_b": b.get("controller"),
        "passed_a": a.get("passed"),
        "passed_b": b.get("passed"),
        "pass_status_changed": a.get("passed") != b.get("passed"),
        "metrics_delta": deltas,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_a", help="path to first result.json")
    parser.add_argument("run_b", help="path to second result.json")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    a = load(args.run_a)
    b = load(args.run_b)
    result = compare(a, b)
    print(json.dumps(result, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
