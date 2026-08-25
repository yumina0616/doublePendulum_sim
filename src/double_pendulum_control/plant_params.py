"""REFACTOR-001: shared loader for plant_params.yaml -- the single source
of truth for the double pendulum's physical parameters, also read
directly by double_pendulum.urdf.xacro via xacro.load_yaml().

Before this, double_pendulum.urdf.xacro and linear_model.py's
PendulumParams each hardcoded their own independent copy of m1/m2/L1/L2/
damping/torque-limit values, with nothing enforcing they stayed in sync
(the exact background SKILL-CONTROL-MODEL-CONSISTENCY was written to
guard against -- see harness/skills/retired/ for why that skill was
retired in favor of this).
"""
from __future__ import annotations

import hashlib
import json
import os

import yaml
from ament_index_python.packages import get_package_share_directory

PLANT_PARAMS_RELATIVE_PATH = os.path.join("config", "plant_params.yaml")


def find_plant_params_path() -> str:
    # local-source-first, matching the convention run_experiment.py's
    # find_scenario_path already uses: works with --symlink-install
    # without a rebuild, falls back to the installed share/ copy.
    local = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "double_pendulum_description",
        PLANT_PARAMS_RELATIVE_PATH,
    )
    local = os.path.normpath(local)
    if os.path.isfile(local):
        return local
    share = os.path.join(get_package_share_directory("double_pendulum_description"),
                          PLANT_PARAMS_RELATIVE_PATH)
    return share


def load_plant_params(path: str | None = None) -> dict:
    path = path or find_plant_params_path()
    with open(path) as f:
        return yaml.safe_load(f)


def plant_hash(params: dict) -> str:
    """Deterministic hash over the plant params dict -- sorted keys, fixed
    float formatting, so the same physical values always hash the same
    regardless of dict insertion order or float repr quirks."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    p = load_plant_params()
    print(f"loaded from: {find_plant_params_path()}")
    print(p)
    print(f"plant_hash: {plant_hash(p)}")
