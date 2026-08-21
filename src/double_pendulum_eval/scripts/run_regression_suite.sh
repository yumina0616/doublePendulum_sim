#!/bin/bash
# Phase 3: regression suite -- runs every scenario against one controller
# config (each via run_clean_experiment.sh, so every scenario gets its own
# fresh Gazebo instance and is directly comparable) and prints a summary
# table at the end. Exits 0 only if every scenario passed. Also writes a
# machine-readable summary.json (see tasks/CTRL-001-regression-summary/).
#
# Usage:
#   run_regression_suite.sh <pd|lqr> [--gui] [--output <path>] [-- extra ros2 args for the controller]
#
# Examples:
#   run_regression_suite.sh pd
#   run_regression_suite.sh lqr -- --ros-args -p q1d:=15.0 -p q2d:=15.0 -p qi1:=5.0 -p qi2:=5.0
#   run_regression_suite.sh pd --output /tmp/my_summary.json
set -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIOS_DIR="$HERE/../scenarios"

CONTROLLER="${1:?usage: run_regression_suite.sh <pd|lqr> [--gui] [--output <path>] [-- extra args]}"
shift
GUI_FLAG=()
OUTPUT_PATH="/tmp/regression_summary.json"
while true; do
  if [ "${1:-}" = "--gui" ]; then
    GUI_FLAG=(--gui)
    shift
  elif [ "${1:-}" = "--output" ]; then
    OUTPUT_PATH="${2:?--output requires a path}"
    shift 2
  else
    break
  fi
done

# every *.yaml in scenarios/ except the leading-underscore diagnostic ones
SCENARIOS=()
for f in "$SCENARIOS_DIR"/*.yaml; do
  name="$(basename "$f" .yaml)"
  case "$name" in
    _*) continue ;;
  esac
  SCENARIOS+=("$name")
done

if [ "${#SCENARIOS[@]}" -eq 0 ]; then
  echo "No scenarios found in $SCENARIOS_DIR" >&2
  exit 2
fi

echo "Regression suite: controller=$CONTROLLER, scenarios=${SCENARIOS[*]}"
echo

declare -A RESULT
declare -A RESULT_BOOL
OVERALL=0
for scenario in "${SCENARIOS[@]}"; do
  echo "=================================================================="
  echo "Scenario: $scenario"
  echo "=================================================================="
  # NOTE: intentionally no extra "--" here -- if the caller passed one
  # (e.g. "-- --ros-args -p q1d:=15.0"), it's already the first element of
  # "$@" and run_clean_experiment.sh consumes exactly one "--" itself.
  bash "$HERE/run_clean_experiment.sh" "$CONTROLLER" "$scenario" "${GUI_FLAG[@]}" "$@"
  code=$?
  if [ $code -eq 0 ]; then
    RESULT[$scenario]="PASS"
    RESULT_BOOL[$scenario]="true"
  else
    RESULT[$scenario]="FAIL (exit $code)"
    RESULT_BOOL[$scenario]="false"
    OVERALL=1
  fi
  echo
done

echo "=================================================================="
echo "Regression suite summary (controller=$CONTROLLER)"
echo "=================================================================="
for scenario in "${SCENARIOS[@]}"; do
  printf "  %-25s %s\n" "$scenario" "${RESULT[$scenario]}"
done
echo
if [ $OVERALL -eq 0 ]; then
  echo "ALL SCENARIOS PASSED"
else
  echo "SOME SCENARIOS FAILED"
fi

# machine-readable summary (CTRL-001)
SCENARIOS_JSON=""
for scenario in "${SCENARIOS[@]}"; do
  if [ -n "$SCENARIOS_JSON" ]; then SCENARIOS_JSON+=","; fi
  SCENARIOS_JSON+="\"$scenario\": ${RESULT_BOOL[$scenario]}"
done
OVERALL_BOOL="true"
if [ $OVERALL -ne 0 ]; then OVERALL_BOOL="false"; fi

cat > "$OUTPUT_PATH" <<EOF
{
  "controller": "$CONTROLLER",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "scenarios": {$SCENARIOS_JSON},
  "overall_pass": $OVERALL_BOOL
}
EOF
echo "Summary written to $OUTPUT_PATH"

exit $OVERALL
