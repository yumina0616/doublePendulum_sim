#!/bin/bash
# CTRL-004: statistical acceptance -- run the same controller+scenario N
# times and require a pass RATE, not a single pass, before declaring a
# verdict. Doesn't fix the underlying run-to-run physics variance found in
# CTRL-003 (unresolved) -- makes the verifier honest about it instead of
# trusting one lucky/unlucky run.
#
# Usage:
#   run_repeated_experiment.sh <pd|lqr> <scenario> [N] [threshold] [--gui] [-- extra ros2 args]
#
# N: number of repeats (default 5). threshold: required pass rate 0.0-1.0
# (default 0.6, i.e. >=60% of runs must pass).
#
# Examples:
#   run_repeated_experiment.sh pd nominal_balance
#   run_repeated_experiment.sh pd nominal_balance 5 0.6
#   run_repeated_experiment.sh lqr nominal_balance 3 0.67 -- --ros-args -p q1d:=15.0
set -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CONTROLLER="${1:?usage: run_repeated_experiment.sh <pd|lqr> <scenario> [N] [threshold] [--gui] [-- extra args]}"
SCENARIO="${2:?usage: run_repeated_experiment.sh <pd|lqr> <scenario> [N] [threshold] [--gui] [-- extra args]}"
shift 2

N=5
if [ "${1:-}" != "" ] && [ "${1:-}" != "--gui" ] && [ "${1:-}" != "--" ]; then
  N="$1"; shift
fi
THRESHOLD=0.6
if [ "${1:-}" != "" ] && [ "${1:-}" != "--gui" ] && [ "${1:-}" != "--" ]; then
  THRESHOLD="$1"; shift
fi
GUI_FLAG=()
if [ "${1:-}" = "--gui" ]; then
  GUI_FLAG=(--gui)
  shift
fi

echo "Repeated experiment: controller=$CONTROLLER scenario=$SCENARIO N=$N threshold=$THRESHOLD"
echo

N_PASSED=0
RESULTS_JSON=""
for i in $(seq 1 "$N"); do
  echo "=================================================================="
  echo "Run $i/$N"
  echo "=================================================================="
  bash "$HERE/run_clean_experiment.sh" "$CONTROLLER" "$SCENARIO" "${GUI_FLAG[@]}" "$@"
  code=$?
  if [ $code -eq 0 ]; then
    N_PASSED=$((N_PASSED + 1))
    verdict_i="true"
  else
    verdict_i="false"
  fi
  if [ -n "$RESULTS_JSON" ]; then RESULTS_JSON+=","; fi
  RESULTS_JSON+="{\"run\": $i, \"passed\": $verdict_i, \"exit_code\": $code}"
  # keep each run's own result.json (not just pass/fail) so later analysis
  # can compare failure SEVERITY across runs, not just the threshold verdict
  if [ -f "/tmp/${SCENARIO}_result.json" ]; then
    cp "/tmp/${SCENARIO}_result.json" "/tmp/repeated_${SCENARIO}_run${i}_result.json"
  fi
  echo
done

PASS_RATE=$(python3 -c "print($N_PASSED / $N)")
VERDICT="FAIL"
VERDICT_BOOL="false"
if python3 -c "exit(0 if $PASS_RATE >= $THRESHOLD else 1)"; then
  VERDICT="PASS"
  VERDICT_BOOL="true"
fi

echo "=================================================================="
echo "Repeated experiment summary: $N_PASSED/$N passed (rate=$PASS_RATE, threshold=$THRESHOLD)"
echo "Verdict: $VERDICT"
echo "=================================================================="

OUTPUT_PATH="/tmp/repeated_${SCENARIO}_summary.json"
cat > "$OUTPUT_PATH" <<EOF
{
  "controller": "$CONTROLLER",
  "scenario": "$SCENARIO",
  "n_runs": $N,
  "n_passed": $N_PASSED,
  "pass_rate": $PASS_RATE,
  "threshold": $THRESHOLD,
  "verdict": "$VERDICT",
  "runs": [$RESULTS_JSON]
}
EOF
echo "Summary written to $OUTPUT_PATH"

if [ "$VERDICT_BOOL" = "true" ]; then
  exit 0
else
  exit 1
fi
