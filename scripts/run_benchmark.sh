#!/bin/bash
set -e

CODE="$1"
REPO="$2"
MODE="$3"
BUILD_TAG="$4"
RUN_TAG="$5"

echo "Running benchmark for $CODE"
cd programs/$CODE

if [[ "$MODE" == "build_and_run" ]]; then
  ./build.sh "$BUILD_TAG"
  ./run.sh "$RUN_TAG"
else
  echo "Unsupported mode in this script: $MODE"
  exit 1
fi
