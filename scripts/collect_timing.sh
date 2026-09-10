#!/bin/bash
# collect_timing.sh - Collect timing information from timestamp files
# Reads build/run timestamp files and generates results/pipeline_timing.json

BUILD_TIME=0
QUEUE_TIME=0
QUEUE_TIME_SOURCE="not_measured"
RUN_TIME=0
SCHEDULER_QUEUE_TIME=""
SCHEDULER_QUEUE_TIME_SOURCE=""

integer_value() {
  local value="$1"
  case "$value" in
    ''|*[!0-9]*)
      printf ''
      ;;
    *)
      printf '%s' "$value"
      ;;
  esac
}

timestamp_value() {
  local path="$1"
  local value=""

  if [ -f "$path" ]; then
    value=$(cat "$path")
  fi

  integer_value "$value"
}

json_integer_value() {
  local path="$1"
  local query="$2"
  local value=""

  [ -f "$path" ] || return 0
  command -v jq >/dev/null 2>&1 || return 0

  value=$(jq -r "$query" "$path" 2>/dev/null || true)
  integer_value "$value"
}

# Build time = build_end - build_start
if [ -f results/build_start ] && [ -f results/build_end ]; then
  bs=$(timestamp_value results/build_start)
  be=$(timestamp_value results/build_end)
  if [ -n "$bs" ] && [ -n "$be" ] && [ "$be" -ge "$bs" ]; then
    BUILD_TIME=$((be - bs))
  fi
fi

# Run time = run_end - run_start
if [ -f results/run_start ] && [ -f results/run_end ]; then
  rs=$(timestamp_value results/run_start)
  re=$(timestamp_value results/run_end)
  if [ -n "$rs" ] && [ -n "$re" ] && [ "$re" -ge "$rs" ]; then
    RUN_TIME=$((re - rs))
  fi
fi

# Scheduler/job queue time = run_start - CI_JOB_STARTED_AT when the run job
# recorded GitLab job timing context before entering the benchmark script.
if [ -f results/ci_timing_context.json ]; then
  ci_job_started_epoch=$(json_integer_value results/ci_timing_context.json 'try (.ci_job_started_epoch // empty) catch empty')
  rs=$(timestamp_value results/run_start)
  if [ -n "$ci_job_started_epoch" ] && [ -n "$rs" ] && [ "$rs" -ge "$ci_job_started_epoch" ]; then
    SCHEDULER_QUEUE_TIME=$((rs - ci_job_started_epoch))
    SCHEDULER_QUEUE_TIME_SOURCE="gitlab_job_started_at"
  fi
fi

# Queue time is not measured here. Sites may attach explicit scheduler
# queue metadata separately as scheduler_queue_time.
QUEUE_TIME=0

if [ -n "$SCHEDULER_QUEUE_TIME" ]; then
cat > results/pipeline_timing.json <<EOF
{
  "build_time": $BUILD_TIME,
  "queue_time": $QUEUE_TIME,
  "queue_time_source": "$QUEUE_TIME_SOURCE",
  "scheduler_queue_time": $SCHEDULER_QUEUE_TIME,
  "scheduler_queue_time_source": "$SCHEDULER_QUEUE_TIME_SOURCE",
  "run_time": $RUN_TIME
}
EOF
else
cat > results/pipeline_timing.json <<EOF
{
  "build_time": $BUILD_TIME,
  "queue_time": $QUEUE_TIME,
  "queue_time_source": "$QUEUE_TIME_SOURCE",
  "run_time": $RUN_TIME
}
EOF
fi

if [ -n "$SCHEDULER_QUEUE_TIME" ]; then
  scheduler_queue_label="${SCHEDULER_QUEUE_TIME}s"
else
  scheduler_queue_label="not_measured"
fi
echo "Timing collected: build=${BUILD_TIME}s queue=${QUEUE_TIME}s scheduler_queue=${scheduler_queue_label} run=${RUN_TIME}s"
