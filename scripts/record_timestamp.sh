#!/bin/bash
# record_timestamp.sh - Record current Unix epoch timestamp to a file
# Usage: bash scripts/record_timestamp.sh <filepath>
# Example: bash scripts/record_timestamp.sh results/build_start

if [ -z "$1" ]; then
  echo "Usage: bash scripts/record_timestamp.sh <filepath>"
  exit 1
fi

mkdir -p "$(dirname "$1")"
date +%s > "$1"
