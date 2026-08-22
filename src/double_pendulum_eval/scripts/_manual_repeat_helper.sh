#!/bin/bash
# Scratch helper: run_repeated_experiment.sh's own background-loop mode is
# currently unreliable in this tool session (background tasks get
# terminated well before completion, though the underlying processes
# survive as orphans that never finish -- see HARNESS-001 investigation
# notes). This is the same thing done via sequential FOREGROUND calls
# instead, which do survive to completion.
#
# Usage: _manual_repeat_helper.sh <controller> <scenario> <start_idx> <end_idx>
set -o pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROLLER="$1"; SCENARIO="$2"; START="$3"; END="$4"

for i in $(seq "$START" "$END"); do
  for attempt in 1 2 3; do
    echo "=================================================================="
    echo "Run $i (attempt $attempt)"
    echo "=================================================================="
    rm -f "/tmp/${SCENARIO}_result.json"  # so a stale file can't be mistaken for this attempt's own output
    bash "$HERE/run_clean_experiment.sh" "$CONTROLLER" "$SCENARIO"
    code=$?
    if [ $code -eq 0 ] || [ $code -eq 1 ]; then
      # 0/1 = a real experiment ran and produced a pass/fail verdict (not an infra abort)
      cp "/tmp/${SCENARIO}_result.json" "/tmp/repeated_${SCENARIO}_run${i}_result.json"
      echo "saved run $i (exit $code)"
      break
    else
      echo "WARNING: run $i attempt $attempt hit an infra failure (exit $code), retrying" >&2
    fi
  done
done
