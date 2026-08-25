#!/bin/bash
# CTRL-004: statistical acceptance -- run the same controller+scenario N
# times and require a pass RATE, not a single pass, before declaring a
# verdict.
#
# INFRA-001: pass_rate is now computed only over runs that actually
# completed a genuine control experiment (verdict PASS_CONTROL/
# FAIL_CONTROL), reading the per-run verdict out of each run's own
# result.json instead of trusting the shell exit code alone. Runs that
# never really exercised the controller (INVALID_INFRA: discovery
# timeouts, zero-torque runs, etc) or that hit a harness bug
# (FAIL_HARNESS) are excluded from the pass_rate denominator and reported
# separately as infra_failure_rate / harness_failure_rate. Before this,
# a run that aborted before Gazebo was even ready counted as a plain
# "FAIL" indistinguishable from the controller genuinely losing balance --
# which is exactly what made CTRL-003/CTRL-004's low pass rates
# untrustworthy as a verdict on control quality.
#
# Usage:
#   run_repeated_experiment.sh <pd|lqr> <scenario> [N] [threshold] [--gui] [-- extra ros2 args]
#
# N: number of repeats (default 5). threshold: required pass rate 0.0-1.0
# among CONTROL-verdict runs only (default 0.6, i.e. >=60% of runs that
# actually ran must pass).
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

# Reads the verdict field out of a run's result.json. Falls back to
# exit-code inference only if the file is missing or predates INFRA-001
# (no verdict field) -- every current code path writes one, so this
# fallback exists purely for robustness against a stale/foreign
# result.json, not as the normal path.
read_verdict() {
  local result_file="$1"
  local exit_code="$2"
  python3 -c "
import json, sys
path, code = sys.argv[1], int(sys.argv[2])
try:
    with open(path) as f:
        data = json.load(f)
    v = data.get('verdict')
    if v in ('PASS_CONTROL', 'FAIL_CONTROL', 'INVALID_INFRA', 'FAIL_HARNESS'):
        print(v)
        sys.exit(0)
except Exception:
    pass
# fallback: no usable verdict field -- infer coarsely from exit code.
print('PASS_CONTROL' if code == 0 else 'FAIL_CONTROL')
" "$result_file" "$exit_code"
}

N_PASS_CONTROL=0
N_FAIL_CONTROL=0
N_INVALID_INFRA=0
N_FAIL_HARNESS=0
RESULTS_JSON=""
for i in $(seq 1 "$N"); do
  echo "=================================================================="
  echo "Run $i/$N"
  echo "=================================================================="
  rm -f "/tmp/${SCENARIO}_result.json"
  bash "$HERE/run_clean_experiment.sh" "$CONTROLLER" "$SCENARIO" "${GUI_FLAG[@]}" "$@"
  code=$?

  RESULT_FILE="/tmp/${SCENARIO}_result.json"
  verdict_i=$(read_verdict "$RESULT_FILE" "$code")
  case "$verdict_i" in
    PASS_CONTROL) N_PASS_CONTROL=$((N_PASS_CONTROL + 1)) ;;
    FAIL_CONTROL) N_FAIL_CONTROL=$((N_FAIL_CONTROL + 1)) ;;
    INVALID_INFRA) N_INVALID_INFRA=$((N_INVALID_INFRA + 1)) ;;
    FAIL_HARNESS) N_FAIL_HARNESS=$((N_FAIL_HARNESS + 1)) ;;
  esac
  echo "  run $i verdict: $verdict_i (exit_code=$code)"

  if [ -n "$RESULTS_JSON" ]; then RESULTS_JSON+=","; fi
  RESULTS_JSON+="{\"run\": $i, \"verdict\": \"$verdict_i\", \"exit_code\": $code}"
  # keep each run's own result.json (not just the verdict) so later
  # analysis can compare failure SEVERITY across runs, not just the
  # aggregate verdict
  if [ -f "$RESULT_FILE" ]; then
    cp "$RESULT_FILE" "/tmp/repeated_${SCENARIO}_run${i}_result.json"
  fi
  echo
done

N_CONTROL=$((N_PASS_CONTROL + N_FAIL_CONTROL))
if [ "$N_CONTROL" -gt 0 ]; then
  PASS_RATE=$(python3 -c "print($N_PASS_CONTROL / $N_CONTROL)")
else
  PASS_RATE="null"
fi
INFRA_FAILURE_RATE=$(python3 -c "print($N_INVALID_INFRA / $N)")
HARNESS_FAILURE_RATE=$(python3 -c "print($N_FAIL_HARNESS / $N)")

VERDICT="FAIL"
VERDICT_BOOL="false"
if [ "$N_CONTROL" -eq 0 ]; then
  # every single run was INVALID_INFRA/FAIL_HARNESS -- there is no control
  # data to judge at all, which is a fundamentally different (and more
  # alarming) situation than "the controller failed the threshold". Must
  # not be silently reported as plain FAIL.
  VERDICT="INCONCLUSIVE_NO_VALID_RUNS"
elif python3 -c "exit(0 if $PASS_RATE >= $THRESHOLD else 1)"; then
  VERDICT="PASS"
  VERDICT_BOOL="true"
fi

echo "=================================================================="
echo "Repeated experiment summary: $N runs -- $N_PASS_CONTROL PASS_CONTROL, $N_FAIL_CONTROL FAIL_CONTROL,"
echo "  $N_INVALID_INFRA INVALID_INFRA, $N_FAIL_HARNESS FAIL_HARNESS"
echo "Control pass_rate (over $N_CONTROL valid runs): $PASS_RATE (threshold=$THRESHOLD)"
echo "Infra failure rate: $INFRA_FAILURE_RATE   Harness failure rate: $HARNESS_FAILURE_RATE"
echo "Verdict: $VERDICT"
echo "=================================================================="

OUTPUT_PATH="/tmp/repeated_${SCENARIO}_summary.json.tmp"
FINAL_OUTPUT_PATH="/tmp/repeated_${SCENARIO}_summary.json"
cat > "$OUTPUT_PATH" <<EOF
{
  "controller": "$CONTROLLER",
  "scenario": "$SCENARIO",
  "n_runs": $N,
  "n_pass_control": $N_PASS_CONTROL,
  "n_fail_control": $N_FAIL_CONTROL,
  "n_invalid_infra": $N_INVALID_INFRA,
  "n_fail_harness": $N_FAIL_HARNESS,
  "n_control_runs": $N_CONTROL,
  "pass_rate": $PASS_RATE,
  "infra_failure_rate": $INFRA_FAILURE_RATE,
  "harness_failure_rate": $HARNESS_FAILURE_RATE,
  "threshold": $THRESHOLD,
  "verdict": "$VERDICT",
  "runs": [$RESULTS_JSON]
}
EOF
mv "$OUTPUT_PATH" "$FINAL_OUTPUT_PATH"
echo "Summary written to $FINAL_OUTPUT_PATH"

if [ "$VERDICT_BOOL" = "true" ]; then
  exit 0
else
  exit 1
fi
