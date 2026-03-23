#!/bin/bash
# collect_timing.sh - Collect timing information from timestamp files
# Reads build/run/queue timestamp files and generates results/timing.env

BUILD_TIME=0
QUEUE_TIME=0
RUN_TIME=0

# Build time = build_end - build_start
if [ -f results/build_start ] && [ -f results/build_end ]; then
  bs=$(cat results/build_start)
  be=$(cat results/build_end)
  BUILD_TIME=$((be - bs))
fi

# Run time = run_end - run_start
if [ -f results/run_start ] && [ -f results/run_end ]; then
  rs=$(cat results/run_start)
  re=$(cat results/run_end)
  RUN_TIME=$((re - rs))
fi

# Queue time: not measurable with current Jacamar/pjsub architecture
# (before_script/script all run inside the batch job, so queue_submit
#  is recorded after the job has already started)
QUEUE_TIME=0

echo "BUILD_TIME=$BUILD_TIME" > results/timing.env
echo "QUEUE_TIME=$QUEUE_TIME" >> results/timing.env
echo "RUN_TIME=$RUN_TIME" >> results/timing.env

echo "Timing collected: build=${BUILD_TIME}s queue=${QUEUE_TIME}s run=${RUN_TIME}s"
