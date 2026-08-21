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

source /opt/ros/humble/setup.bash
source ~/agentic_double_pendulum/install/setup.bash

echo "[1/4] Cleaning up any leftover processes..."
pkill -9 -f '[r]os2 launch double_pendulum' 2>/dev/null
pkill -9 -f '[g]z sim' 2>/dev/null
pkill -9 -f '[c]ontroller_node.py' 2>/dev/null
pkill -9 -f '[l]qr_node.py' 2>/dev/null
sleep 2

echo "[2/4] Launching a fresh Gazebo simulation (headless:=$HEADLESS)..."
ros2 launch double_pendulum_description spawn.launch.py headless:="$HEADLESS" > /tmp/gz_launch.log 2>&1 &
GZ_PID=$!
sleep 5  # let the graph settle before subscribing -- `ros2 topic echo --once`
         # called immediately after launch can race DDS discovery and hang
         # the full 60s even though the topic starts flowing a few seconds in

echo "  waiting for /joint_states to actually publish data (topic existing isn't enough --"
echo "  GUI mode in particular can take a while past that before physics/bridge is really live)..."
if timeout 60 ros2 topic echo /joint_states --once > /dev/null 2>&1; then
  echo "  /joint_states is flowing"
else
  echo "ERROR: no /joint_states data within 60s -- aborting instead of running" >&2
  echo "  the experiment against a plant that isn't actually simulating yet." >&2
  tail -20 /tmp/gz_launch.log >&2
  kill "$GZ_PID" 2>/dev/null
  pkill -9 -f '[r]os2 launch double_pendulum' 2>/dev/null
  pkill -9 -f '[g]z sim' 2>/dev/null
  exit 4
fi
sleep 2  # let controller_manager finish loading joint_state_broadcaster + effort_controller

echo "[3/4] Starting $CONTROLLER controller..."
if [ "$CONTROLLER" = "pd" ]; then
  ros2 run double_pendulum_control controller_node.py "${EXTRA_ARGS[@]}" > /tmp/ctrl_launch.log 2>&1 &
  CTRL_PID=$!
  sleep 2
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
    kill "$CTRL_PID" "$GZ_PID" 2>/dev/null
    pkill -9 -f '[r]os2 launch double_pendulum' 2>/dev/null
    pkill -9 -f '[g]z sim' 2>/dev/null
    exit 3
  fi
else
  echo "Unknown controller '$CONTROLLER' (expected pd|lqr)" >&2
  kill "$GZ_PID" 2>/dev/null
  exit 2
fi

echo "[4/4] Running experiment: $SCENARIO"
ros2 run double_pendulum_eval run_experiment.py --scenario "$SCENARIO" --controller "$CONTROLLER"
RESULT=$?

echo "Cleaning up..."
kill "$CTRL_PID" 2>/dev/null
kill "$GZ_PID" 2>/dev/null
sleep 1
pkill -9 -f '[r]os2 launch double_pendulum' 2>/dev/null
pkill -9 -f '[g]z sim' 2>/dev/null

exit $RESULT
