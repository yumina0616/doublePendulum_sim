#!/bin/bash
# DIAG-002: runs N clean LQR/nominal_balance experiments via the existing,
# unmodified run_clean_experiment.sh, and for each run launches
# record_trajectory.py concurrently to record both real joint values AND
# arrival timing during that run's active experiment window -- same
# orchestration pattern as DIAG-001's run_diag001.sh, reused verbatim,
# just pointed at record_trajectory.py instead of measure_jitter.py.
#
# Usage:
#   run_diag002.sh [N]
set -o pipefail

N="${1:-5}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
TASK_DIR="$(cd "$HERE/.." && pwd)"
EVIDENCE_DIR="$TASK_DIR/evidence"
mkdir -p "$EVIDENCE_DIR"

CLEAN_SCRIPT="$REPO_ROOT/src/double_pendulum_eval/scripts/run_clean_experiment.sh"
if [ ! -x "$CLEAN_SCRIPT" ]; then
  echo "ERROR: $CLEAN_SCRIPT not found or not executable" >&2
  exit 1
fi

RECORD_DURATION_S=9.0

source /opt/ros/humble/setup.bash
source "$REPO_ROOT/install/setup.bash"

for i in $(seq 1 "$N"); do
  RUN_LOG="/tmp/diag002_clean_run_${i}.log"
  RAW_OUT="$EVIDENCE_DIR/run_${i}_raw_trajectory.json"

  echo "=== DIAG-002 run $i/$N ==="
  "$CLEAN_SCRIPT" lqr nominal_balance > "$RUN_LOG" 2>&1 &
  CLEAN_PID=$!

  echo "  waiting for the scenario to actually start running..."
  STARTED=false
  for w in $(seq 1 200); do
    if grep -q "\[4/4\] Running experiment" "$RUN_LOG" 2>/dev/null; then
      STARTED=true
      break
    fi
    if ! kill -0 "$CLEAN_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done

  if [ "$STARTED" != "true" ]; then
    echo "  WARNING: run $i never reached '[4/4] Running experiment' -- skipping recording for this run" >&2
    wait "$CLEAN_PID"
    echo "  (clean script exit code: $?)"
    tail -20 "$RUN_LOG" >&2
    continue
  fi

  echo "  scenario running -- recording trajectory for ${RECORD_DURATION_S}s..."
  python3 "$HERE/record_trajectory.py" --duration "$RECORD_DURATION_S" --out "$RAW_OUT"

  echo "  waiting for run_clean_experiment.sh (pid $CLEAN_PID) to finish its own teardown..."
  wait "$CLEAN_PID"
  CLEAN_EXIT=$?
  echo "  run $i done (clean script exit code: $CLEAN_EXIT)"
done

echo "All $N runs attempted. Raw trajectory files in $EVIDENCE_DIR/run_*_raw_trajectory.json"
