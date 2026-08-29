#!/usr/bin/env python3
"""PHYS-002: aggregate the three comparison arms into evidence/comparison.json.

Does NOT pre-judge Case 1/2/3 -- just lays the numbers side by side.
Interpretation happens in PLAN.md/result.json by a human/agent reading
this output, per LQI_ROOT_CAUSE_PLAN.md's explicit instruction not to
force a conclusion in code.
"""
import json
import math
import os

TASK_DIR = os.path.expanduser("~/agentic_double_pendulum/tasks/PHYS-002-closed-loop-physics-only")
EVIDENCE = os.path.join(TASK_DIR, "evidence")


def load(path):
    with open(path) as f:
        return json.load(f)


def finite_or_inf(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isinf(v):
        return "inf"
    return v


def main():
    offline = load(os.path.join(EVIDENCE, "offline_prediction.json"))

    physics_only_runs = []
    for i in range(1, 6):
        d = load(os.path.join(EVIDENCE, f"physics_only_run_{i}.json"))
        physics_only_runs.append(d["metrics"])

    ros_batch_dir = os.path.join(EVIDENCE, "ros2_e2e_lqr_batch")
    ros_summary = load(os.path.join(ros_batch_dir, "summary.json"))
    ros_runs = []
    for entry in ros_summary["runs"]:
        rf = entry["result_file"]
        # result_file has the original absolute path from before copying;
        # redirect to the archived copy under this task's evidence/.
        local = os.path.join(ros_batch_dir, f"run{entry['run']}", "result.json")
        d = load(local)
        m = d.get("metrics")
        ros_runs.append({
            "run": entry["run"],
            "verdict": entry["verdict"],
            "metrics": m,
        })

    def summarize(runs_metrics):
        vals = [m["settling_time_q1_s"] for m in runs_metrics if m is not None]
        finite_vals = [v for v in vals if not (isinstance(v, float) and math.isinf(v))]
        return {
            "n_runs": len(runs_metrics),
            "n_valid": len(vals),
            "settling_time_q1_s_all": [finite_or_inf(v) for v in vals],
            "settling_time_q1_s_finite_only": finite_vals,
            "n_never_settled_within_window": sum(1 for v in vals if isinstance(v, float) and math.isinf(v)),
        }

    physics_only_summary = summarize(physics_only_runs)
    ros_metrics_list = [r["metrics"] for r in ros_runs]
    ros_summary_stats = summarize(ros_metrics_list)

    comparison = {
        "scenario": "nominal_balance",
        "acceptance_threshold_settling_time_q1_s": 3.0,
        "arms": {
            "offline_prediction": {
                "label": "offline (no Gazebo, no ROS2) -- autotune_lqr.simulate_closed_loop, actual cached K + current plant_params.yaml",
                "deterministic": True,
                "settling_time_q1_s": offline["metrics"]["settling_time_q1_s"],
                "settling_time_q2_s": offline["metrics"]["settling_time_q2_s"],
                "overshoot_q1_deg": offline["metrics"]["overshoot_q1_deg"],
                "final_q1_deg": offline["metrics"]["final_q1_deg"],
                "passed": offline["passed"],
            },
            "closed_loop_physics_only": {
                "label": "Gazebo physics engine, exact fixed 10ms control, no ROS2/DDS (gz-transport only)",
                "deterministic": True,
                **physics_only_summary,
                "overshoot_q1_deg": physics_only_runs[0]["overshoot_q1_deg"],
                "final_q1_deg": physics_only_runs[0]["final_q1_deg"],
            },
            "ros2_e2e_real": {
                "label": "real ROS2/DDS end-to-end (run_clean_experiment.sh / run_repeated_experiment.sh, unmodified)",
                "deterministic": False,
                "n_invalid_infra": sum(1 for r in ros_runs if r["verdict"] == "INVALID_INFRA"),
                **ros_summary_stats,
            },
        },
        "note": "Case 1/2/3 classification is NOT decided here -- see PLAN.md/result.json interpretation section.",
    }

    out = os.path.join(EVIDENCE, "comparison.json")
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(comparison, f, indent=2)
    os.replace(tmp, out)
    print(json.dumps(comparison, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
