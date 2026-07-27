#!/bin/bash
set -euo pipefail

if [ "$#" -ne 6 ]; then
  echo "Usage: $0 <program> <system> <mode> <build_job> <run_job> <pipeline_id>" >&2
  exit 1
fi

project_dir=$PWD
work_dir="${project_dir}/send_results_workspace"

rm -rf "$work_dir"
mkdir -p "$work_dir"
cp -R results "$work_dir/results"

cd "$work_dir"
bash "$project_dir/scripts/collect_timing.sh"
bash "$project_dir/scripts/result.sh" "$@"
bash "$project_dir/scripts/result_server/send_results.sh"
