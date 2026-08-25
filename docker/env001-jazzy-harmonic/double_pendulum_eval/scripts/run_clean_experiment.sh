#!/bin/bash
# Phase 3: fully-automated, clean-state experiment run.
#
# Kills any leftover Gazebo/controller processes, launches a *fresh* Gazebo
# instance (guaranteed clean state -- avoids the unreliable gz world-reset
# service, which doesn't reliably reset entities spawned dynamically via
# `create` after the world already started), starts the requested
# controller, waits for it to be ready, runs the scenario, then tears
# everything down. This is what makes LQR/PD gain sweeps comparable --
# without it, each run inherits residual position/velocity from whatever
# the previous run left behind.
#
# Usage:
#   run_clean_experiment.sh <pd|lqr> <scenario> [--gui] [-- extra ros2 args for the controller]
#
# --gui opens the Gazebo 3D window (headless:=false) so you can watch it
# live; without it, Gazebo runs headless (faster, no GPU involved).
#
# Examples:
#   run_clean_experiment.sh pd nominal_balance
#   run_clean_experiment.sh lqr nominal_balance --gui -- --ros-args -p q1d:=15.0 -p q2d:=15.0
#
# INFRA-003 (run isolation): every invocation gets its own run_id and
# output directory (results/raw/<run_id>/, never overwritten by a later
# run), plus an environment_manifest.json recording ROS distro/Gazebo
# version/physics settings alongside the result. Set DPEND_RUN_ID /
# DPEND_RUN_DIR to override either explicitly (used by
# run_repeated_experiment.sh to isolate each of its N runs).
#
# NOT done: per-run ROS_DOMAIN_ID rotation, despite NEXT_STEPS.md asking
# for it. Tested directly: under this project's WSL2 + Gazebo 8.14 +
# ROS2 Humble combination, launching with any non-default ROS_DOMAIN_ID
# reliably breaks /clock discovery entirely (never became available in
# 45s of polling, vs 5s under the default domain 0) -- some part of the
# gz_ros2_control / ros_gz_bridge chain here doesn't propagate a
# non-zero domain id the way a plain ROS2 node would. Rotating domains
# would have made every run INVALID_INFRA, which defeats the entire
# point of a "run isolation" feature. Documented rather than silently
# dropped -- worth retrying if this project ever moves off this exact
# distro/Gazebo combination (see NEXT_STEPS.md item 5, ENV-001).
set -o pipefail

CONTROLLER="${1:?usage: run_clean_experiment.sh <pd|lqr> <scenario> [--gui] [-- extra args]}"
SCENARIO="${2:?usage: run_clean_experiment.sh <pd|lqr> <scenario> [--gui] [-- extra args]}"
shift 2
HEADLESS=true
if [ "${1:-}" = "--gui" ]; then
  HEADLESS=false
  shift
fi
if [ "${1:-}" = "--" ]; then shift; fi
EXTRA_ARGS=("$@")

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE" && git rev-parse --show-toplevel 2>/dev/null || echo "$HOME/agentic_double_pendulum")"

RUN_ID="${DPEND_RUN_ID:-${CONTROLLER}_${SCENARIO}_$(date -u +%Y%m%dT%H%M%SZ)_$$}"
RUN_DIR="${DPEND_RUN_DIR:-$REPO_ROOT/results/raw/$RUN_ID}"
mkdir -p "$RUN_DIR"
OUTPUT_JSON="$RUN_DIR/result.json"

source /opt/ros/humble/setup.bash
source ~/agentic_double_pendulum/install/setup.bash

echo "  run_id=$RUN_ID  ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<default>}  output=$OUTPUT_JSON"

write_environment_manifest() {
  local world_sdf="$REPO_ROOT/src/double_pendulum_description/launch/empty_world.sdf"
  local max_step real_time_factor
  max_step=$(grep -oE '<max_step_size>[^<]+' "$world_sdf" 2>/dev/null | grep -oE '[0-9.]+')
  real_time_factor=$(grep -oE '<real_time_factor>[^<]+' "$world_sdf" 2>/dev/null | grep -oE '[0-9.]+')
  python3 -c "
import json, os, subprocess, sys, time
gz_version = subprocess.run(['gz', 'sim', '--version'], capture_output=True, text=True).stdout.splitlines()
gz_version = gz_version[0] if gz_version else 'unknown'
manifest = {
    'run_id': sys.argv[1],
    'controller': sys.argv[2],
    'scenario': sys.argv[3],
    'headless': sys.argv[4],
    'ros_distro': os.environ.get('ROS_DISTRO', 'unknown'),
    'ros_domain_id': os.environ.get('ROS_DOMAIN_ID', 'unknown'),
    'gazebo_version': gz_version,
    'use_sim_time': True,
    'physics_engine': 'ode',
    'max_step_size_s': sys.argv[5] or None,
    'real_time_factor': sys.argv[6] or None,
    'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
}
tmp = sys.argv[7] + '.tmp'
with open(tmp, 'w') as f:
    json.dump(manifest, f, indent=2)
os.replace(tmp, sys.argv[7])
" "$RUN_ID" "$CONTROLLER" "$SCENARIO" "$HEADLESS" "$max_step" "$real_time_factor" "$RUN_DIR/environment_manifest.json"
}
write_environment_manifest

# INFRA-001: every one of this script's own pre-flight abort paths used to
# bail out with nothing but a stderr message -- no result.json at all.
# Write the same result.json shape run_experiment.py itself writes (see
# write_infra_failure_result there) so every run -- however it fails --
# leaves one consistent, verdict-tagged artifact behind, at the same
# isolated path a successful run would have used (INFRA-003).
write_infra_abort_result() {
  local verdict="$1"
  local reason="$2"
  python3 -c "
import json, os, sys, time
result = {
    'scenario': sys.argv[1],
    'controller': sys.argv[2],
    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
    'n_samples_joint_states': 0,
    'n_samples_effort': 0,
    'metrics': None,
    'acceptance': None,
    'passed': False,
    'failures': [sys.argv[4]],
    'verdict': sys.argv[3],
}
tmp = sys.argv[5] + '.tmp'
with open(tmp, 'w') as f:
    json.dump(result, f, indent=2)
os.replace(tmp, sys.argv[5])
" "$SCENARIO" "$CONTROLLER" "$verdict" "$reason" "$OUTPUT_JSON"
  # best-effort legacy mirror -- some older tooling/manual workflows still
  # look at the fixed /tmp path; the isolated copy above is the source of
  # truth and is never overwritten by a later run.
  cp "$OUTPUT_JSON" "/tmp/${SCENARIO}_result.json" 2>/dev/null
}

# INFRA-003: every abort path used to kill only GZ_PID/CTRL_PID plus a
# partial pkill list that didn't match the final cleanup's list -- which is
# exactly how 2 leftover robot_state_publisher processes survived an
# aborted run during INFRA-002's own verification (their pkill pattern was
# only present in the success-path cleanup, not the abort paths). One
# shared teardown function, called from every exit path, so that can't
# happen again. Kills by PID first (so a fast, targeted shutdown is tried),
# then a pattern-based sweep as a backstop for grandchildren `kill` on the
# direct child PID doesn't reach (ros2 launch's own children).
teardown_all() {
  [ -n "${GZ_PID:-}" ] && kill "$GZ_PID" 2>/dev/null
  [ -n "${CTRL_PID:-}" ] && kill "$CTRL_PID" 2>/dev/null
  sleep 1
  pkill -9 -f '[r]os2 launch double_pendulum' 2>/dev/null
  pkill -9 -f '[g]z sim' 2>/dev/null
  pkill -9 -f '[c]ontroller_node.py' 2>/dev/null
  pkill -9 -f '[l]qr_node.py' 2>/dev/null
  pkill -9 -f 'parameter_bridge' 2>/dev/null
  pkill -9 -f 'robot_state_publisher' 2>/dev/null
}

echo "[1/4] Cleaning up any leftover processes..."
teardown_all
sleep 1

echo "[2/4] Launching a fresh Gazebo simulation (headless:=$HEADLESS)..."
ros2 launch double_pendulum_description spawn.launch.py headless:="$HEADLESS" > /tmp/gz_launch.log 2>&1 &
GZ_PID=$!

# INFRA-002: replaces a family of ad hoc sleeps/single-shot polls with
# explicit checks against real readiness signals (CLI output shapes
# confirmed by direct probing, not assumed):
#   - /clock advancing: `ros2 topic echo /clock --once` yields
#     `clock:\n  sec: N\n  nanosec: M`; read twice ~1s apart and require
#     the nanosecond-resolution value to have strictly increased.
#   - controller 'active': `ros2 control list_controllers` output is
#     ANSI-colored; strip escape codes before grepping for
#     "<name> ... active" on one line.
#   - pub+sub actually connected (not just "a publisher exists somewhere"):
#     `ros2 topic info --verbose <topic>` reports "Publisher count: N" and
#     "Subscription count: N" as separate lines -- require both >= 1.
# Condition 3/6 from NEXT_STEPS.md ("not stale from a previous run" /
# "timestamp after this run's start") is not implemented as a separate
# timestamp check: this script already guarantees it structurally by
# fully pkilling and relaunching Gazebo (and therefore resetting the sim
# clock to 0) before every single run.
read_clock_ns() {
  timeout 3 ros2 topic echo /clock --once 2>/dev/null | awk '
    /^clock:/ { f=1; next }
    f && /^[[:space:]]*sec:/ { sec=$2 }
    f && /^[[:space:]]*nanosec:/ { print (sec+0)*1000000000+($2+0); exit }
  '
}

wait_for_clock_advancing() {
  local timeout_s="$1"
  local waited=0
  local t1 t2
  while [ "$waited" -lt "$timeout_s" ]; do
    t1=$(read_clock_ns)
    if [ -n "$t1" ]; then
      sleep 1
      t2=$(read_clock_ns)
      if [ -n "$t2" ] && [ "$t2" -gt "$t1" ]; then
        echo "  /clock is advancing (${t1}ns -> ${t2}ns)"
        return 0
      fi
    else
      sleep 1
    fi
    waited=$((waited + 1))
  done
  return 1
}

wait_for_controller_active() {
  local name="$1"
  local timeout_s="$2"
  local waited=0
  while [ "$waited" -lt "$timeout_s" ]; do
    if timeout 3 ros2 control list_controllers 2>/dev/null \
        | sed -E 's/\x1b\[[0-9;]*m//g' \
        | grep -qE "^${name}[[:space:]].*[[:space:]]active[[:space:]]*$"; then
      echo "  controller '$name' is active (after ${waited}s)"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

wait_for_topic_pub_and_sub() {
  local topic="$1"
  local timeout_s="$2"
  local waited=0
  local info pub_count sub_count
  while [ "$waited" -lt "$timeout_s" ]; do
    info=$(timeout 3 ros2 topic info --verbose "$topic" 2>/dev/null)
    pub_count=$(echo "$info" | grep -oE "Publisher count: [0-9]+" | grep -oE "[0-9]+")
    sub_count=$(echo "$info" | grep -oE "Subscription count: [0-9]+" | grep -oE "[0-9]+")
    if [ -n "$pub_count" ] && [ -n "$sub_count" ] && [ "$pub_count" -ge 1 ] && [ "$sub_count" -ge 1 ]; then
      echo "  $topic has $pub_count publisher(s) and $sub_count subscriber(s) connected (after ${waited}s)"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

echo "  waiting for /clock to actually be advancing (proves the sim is running, not just launched)..."
if ! wait_for_clock_advancing 30; then
  echo "ERROR: /clock never showed advancing sim time within 30s -- aborting instead of" >&2
  echo "  running the experiment against a plant that isn't actually simulating yet." >&2
  tail -20 /tmp/gz_launch.log >&2
  write_infra_abort_result "INVALID_INFRA" "/clock did not show advancing sim time within 30s of Gazebo launch"
  teardown_all
  exit 4
fi

echo "  waiting for /joint_states to actually publish data (topic existing isn't enough --"
echo "  GUI mode in particular can take a while past that before physics/bridge is really live)..."
if timeout 60 ros2 topic echo /joint_states --once > /dev/null 2>&1; then
  echo "  /joint_states is flowing"
else
  echo "ERROR: no /joint_states data within 60s -- aborting instead of running" >&2
  echo "  the experiment against a plant that isn't actually simulating yet." >&2
  tail -20 /tmp/gz_launch.log >&2
  write_infra_abort_result "INVALID_INFRA" "no /joint_states data within 60s of Gazebo launch"
  teardown_all
  exit 4
fi

echo "  waiting for joint_state_broadcaster and effort_controller to both be 'active'..."
if ! wait_for_controller_active "joint_state_broadcaster" 20 || ! wait_for_controller_active "effort_controller" 20; then
  echo "ERROR: controller_manager never reported both controllers active within 20s" >&2
  write_infra_abort_result "INVALID_INFRA" "controller_manager did not report joint_state_broadcaster+effort_controller active within 20s"
  teardown_all
  exit 4
fi

echo "[3/4] Starting $CONTROLLER controller..."
if [ "$CONTROLLER" = "pd" ]; then
  ros2 run double_pendulum_control controller_node.py "${EXTRA_ARGS[@]}" > /tmp/ctrl_launch.log 2>&1 &
  CTRL_PID=$!
elif [ "$CONTROLLER" = "lqr" ]; then
  ros2 run double_pendulum_control lqr_node.py "${EXTRA_ARGS[@]}" > /tmp/ctrl_launch.log 2>&1 &
  CTRL_PID=$!
  echo "  LQR gain design takes ~1 min, waiting (up to 150s)..."
  LQR_READY=false
  for i in $(seq 1 150); do
    if grep -q "LQR ready" /tmp/ctrl_launch.log 2>/dev/null; then
      echo "  LQR ready (after ${i}s)"
      LQR_READY=true
      break
    fi
    sleep 1
  done
  if [ "$LQR_READY" != "true" ]; then
    echo "ERROR: LQR did not report ready within 150s -- aborting instead of" >&2
    echo "  running the experiment against an untuned/silent controller." >&2
    echo "  --- last lines of ctrl_launch.log ---" >&2
    tail -20 /tmp/ctrl_launch.log >&2
    write_infra_abort_result "INVALID_INFRA" "LQR did not report ready within 150s"
    teardown_all
    exit 3
  fi
else
  echo "Unknown controller '$CONTROLLER' (expected pd|lqr)" >&2
  write_infra_abort_result "FAIL_HARNESS" "unknown controller argument '$CONTROLLER' (expected pd|lqr)"
  teardown_all
  exit 2
fi

# CTRL-005/INFRA-002: confirm the controller's own /effort_controller/commands
# publisher AND the ros2_control subscriber are both actually connected --
# stronger than the old check (a bare `ros2 topic echo --once` only proves
# *a* publisher exists somewhere, not that ros2_control's own subscription
# has completed discovery on it too).
echo "  waiting for $CONTROLLER's /effort_controller/commands publisher and subscriber to both connect..."
if ! wait_for_topic_pub_and_sub "/effort_controller/commands" 30; then
  echo "ERROR: $CONTROLLER controller's /effort_controller/commands never showed both a" >&2
  echo "  publisher and subscriber connected within 30s -- aborting instead of running" >&2
  echo "  the experiment against a controller that may not be fully discovered yet." >&2
  echo "  --- last lines of ctrl_launch.log ---" >&2
  tail -20 /tmp/ctrl_launch.log >&2
  write_infra_abort_result "INVALID_INFRA" "$CONTROLLER controller's /effort_controller/commands never showed both pub+sub connected within 30s"
  teardown_all
  exit 5
fi

echo "[4/4] Running experiment: $SCENARIO"
ros2 run double_pendulum_eval run_experiment.py --scenario "$SCENARIO" --controller "$CONTROLLER" --output "$OUTPUT_JSON"
RESULT=$?
cp "$OUTPUT_JSON" "/tmp/${SCENARIO}_result.json" 2>/dev/null

echo "Cleaning up..."
teardown_all

exit $RESULT
