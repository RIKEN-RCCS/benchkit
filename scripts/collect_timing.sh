#!/bin/bash
# collect_timing.sh - Collect timing information from timestamp files
# Reads build/run/queue timestamp files and generates results/pipeline_timing.json

BUILD_TIME=0
QUEUE_TIME=0
RUN_TIME=0

timestamp_value() {
  local path="$1"
  local value=""

  if [ -f "$path" ]; then
    value=$(cat "$path")
  fi

  case "$value" in
    ''|*[!0-9]*)
      printf ''
      ;;
    *)
      printf '%s' "$value"
      ;;
  esac
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

# Queue time: not measurable with current Jacamar/pjsub architecture
# (before_script/script all run inside the batch job, so queue_submit
#  is recorded after the job has already started)
QUEUE_TIME=0

cat > results/pipeline_timing.json <<EOF
{
  "build_time": $BUILD_TIME,
  "queue_time": $QUEUE_TIME,
  "run_time": $RUN_TIME
}
EOF

echo "Timing collected: build=${BUILD_TIME}s queue=${QUEUE_TIME}s run=${RUN_TIME}s"
