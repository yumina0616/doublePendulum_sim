#!/bin/bash
# PHYS-002: run N repeats of the closed-loop physics-only harness,
# relaunching Gazebo fresh each time (same isolation convention PHYS-001
# and DIAG-001 already use). Does NOT touch run_clean_experiment.sh's own
# logic -- the ROS2 e2e comparison arm is collected separately via that
# unmodified script.
N="${1:-5}"
START="${2:-1}"
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVIDENCE_DIR="$TASK_DIR/evidence"
RUNNER="$TASK_DIR/scripts/closed_loop_physics_only_runner.py"
mkdir -p "$EVIDENCE_DIR"

source /opt/ros/humble/setup.bash >/dev/null 2>&1
source ~/agentic_double_pendulum/install/setup.bash >/dev/null 2>&1

cleanup() {
  pkill -9 -f "[g]z sim" 2>/dev/null
  pkill -9 -f "[r]os2 launch" 2>/dev/null
  pkill -9 -f "[r]obot_state_publisher" 2>/dev/null
  sleep 1
}

for i in $(seq "$START" "$N"); do
  echo "=== PHYS-002 physics-only run $i/$N ==="
  cleanup
  ros2 launch double_pendulum_description spawn.launch.py headless:=true > /tmp/phys002_launch_$i.log 2>&1 &
  LAUNCHPID=$!
  sleep 8
  python3 "$RUNNER" --scenario nominal_balance --output "$EVIDENCE_DIR/physics_only_run_$i.json"
  RC=$?
  kill -9 "$LAUNCHPID" 2>/dev/null
  cleanup
  if [ $RC -ne 0 ]; then
    echo "run $i FAILED (exit $RC) -- see /tmp/phys002_launch_$i.log"
  fi
done

echo "=== all $N physics-only runs done ==="
