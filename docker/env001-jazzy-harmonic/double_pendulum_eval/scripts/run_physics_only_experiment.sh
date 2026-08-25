#!/bin/bash
# PHYS-001: launches a fresh Gazebo instance (same clean-relaunch pattern
# run_clean_experiment.sh uses -- gz.msgs.WorldReset was tried for
# in-process repeats and found to break topic publishing in this Gazebo
# version; a fresh relaunch per run is what's actually reliable here) and
# runs physics_only_runner.py against it: torque injection, stepping, and
# state readout all go through gz-transport directly, never touching
# ROS2/DDS. Output is isolated the same way INFRA-003 isolates
# run_clean_experiment.sh's output (results/raw/<run_id>/).
#
# Usage:
#   run_physics_only_experiment.sh
set -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE" && git rev-parse --show-toplevel 2>/dev/null || echo "$HOME/agentic_double_pendulum")"

RUN_ID="${DPEND_RUN_ID:-physonly_$(date -u +%Y%m%dT%H%M%SZ)_$$}"
RUN_DIR="${DPEND_RUN_DIR:-$REPO_ROOT/results/raw/$RUN_ID}"
mkdir -p "$RUN_DIR"
OUTPUT_JSON="$RUN_DIR/result.json"

source /opt/ros/humble/setup.bash
source ~/agentic_double_pendulum/install/setup.bash

teardown_all() {
  [ -n "${GZ_PID:-}" ] && kill "$GZ_PID" 2>/dev/null
  sleep 1
  pkill -9 -f '[r]os2 launch double_pendulum' 2>/dev/null
  pkill -9 -f '[g]z sim' 2>/dev/null
  pkill -9 -f 'parameter_bridge' 2>/dev/null
  pkill -9 -f 'robot_state_publisher' 2>/dev/null
}

echo "[1/3] Cleaning up any leftover processes..."
teardown_all
sleep 1

echo "[2/3] Launching a fresh Gazebo simulation (headless)..."
ros2 launch double_pendulum_description spawn.launch.py headless:=true > /tmp/phys_only_gz.log 2>&1 &
GZ_PID=$!

if timeout 60 ros2 topic echo /joint_states --once > /dev/null 2>&1; then
  echo "  /joint_states is flowing (model spawned)"
else
  echo "ERROR: no /joint_states data within 60s -- model never spawned" >&2
  tail -20 /tmp/phys_only_gz.log >&2
  teardown_all
  exit 4
fi
# a brief settle so the just-spawned model's pose/wrench services are
# fully live before physics_only_runner.py starts issuing gz-transport
# calls against them (its own run_once() also reads back the initial
# pose before injecting anything, so a residual race here would show up
# as a nonzero initial_q1/q2 rather than fail silently)
sleep 2

echo "[3/3] Running physics-only experiment..."
python3 "$HERE/physics_only_runner.py" --output "$OUTPUT_JSON"
RESULT=$?

echo "Cleaning up..."
teardown_all

exit $RESULT
