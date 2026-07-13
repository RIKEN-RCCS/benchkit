#!/bin/bash
# Submit an app build job for RC systems.

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <code> <line_number>"
  echo "  <code>: program name (directory under programs/)"
  echo "  <line_number>: line number in programs/<code>/list.csv (1-based, excluding header)"
  echo ""
  echo "Example: $0 salmon 4"
  echo "  This will submit a build job for the 4th configuration line from programs/salmon/list.csv"
  exit 1
fi

code=$1
list_csv_line_num=$2

if ! [[ "$list_csv_line_num" =~ ^[0-9]+$ ]]; then
  echo "Error: <line_number> must be a positive integer, got: '$list_csv_line_num'"
  echo "Note: Use line number (1-based), not system name"
  echo "Example: $0 $code 1"
  exit 1
fi

if [ "$list_csv_line_num" -le 0 ]; then
  echo "Error: <line_number> must be greater than 0, got: $list_csv_line_num"
  exit 1
fi

source ./scripts/job_functions.sh
SYSTEM_FILE="config/system.csv"
SYSTEM_INFO_FILE="config/system_info.csv"

if [ ! -d "programs/$code" ]; then
  echo "Error: programs/$code does not exist"
  echo "Available programs:"
  ls -1 programs/ 2>/dev/null | grep -v "^$" | head -10
  exit 1
fi

list_file="programs/$code/list.csv"
if [ ! -f "$list_file" ]; then
  echo "Error: $list_file does not exist"
  exit 1
fi

build_script="programs/$code/build.sh"
if [ ! -f "$build_script" ]; then
  echo "Error: $build_script does not exist"
  exit 1
fi

total_lines=$(tail -n +2 "$list_file" | wc -l)
if [ "$list_csv_line_num" -gt "$total_lines" ]; then
  echo "Error: Line $list_csv_line_num does not exist in $list_file"
  echo "Available lines: 1 to $total_lines"
  echo ""
  echo "Contents of $list_file:"
  echo "Line# | Configuration"
  echo "------|-------------"
  echo "  H   | $(head -1 "$list_file")"
  tail -n +2 "$list_file" | nl -v1 -w5 -s' | '
  exit 1
fi

line=$(tail -n +2 "$list_file" | sed -n "${list_csv_line_num}p")
if [ -z "$line" ]; then
  echo "Error: Line $list_csv_line_num does not exist in $list_file"
  exit 1
fi

IFS=, read -r -a cols <<< "$line"

system="${cols[0]}"
enable="${cols[1]}"
run_nodes="${cols[2]}"
run_numproc_node="${cols[3]}"
run_nthreads="${cols[4]}"
elapse="${cols[5]}"

if [[ "$enable" != "yes" ]]; then
  echo "Notice: Line $list_csv_line_num has enable=$enable, skipping"
  exit 1
fi

mode=$(get_system_mode "$system")
queue_group=$(get_system_queue_group "$system")

if [[ -z "$mode" || -z "$queue_group" ]]; then
  echo "Error: mode or queue_group not found for system=$system in $SYSTEM_FILE"
  exit 1
fi

build_nodes=1
build_cpus_per_task="${BK_BUILD_CPUS_PER_TASK:-8}"

echo "Selected configuration from $list_file (line $list_csv_line_num):"
echo "  $line"
echo ""
echo "Parsed values:"
echo "  system=$system, enable=$enable, mode=$mode (from system.csv), queue_group=$queue_group (from system.csv)"
echo "  run_nodes=$run_nodes, run_numproc_node=$run_numproc_node, run_nthreads=$run_nthreads, elapse=$elapse"
echo ""
echo "Build submission values:"
echo "  nodes=$build_nodes, ntasks_per_node=1, cpus_per_task=$build_cpus_per_task"

case "$system" in
  RC_GH200|RC_DGXSP|RC_GENOA)
    echo sbatch -p "$queue_group" -N "$build_nodes" -t "$elapse" --ntasks-per-node=1 --cpus-per-task="$build_cpus_per_task" \
      --wrap="bash programs/$code/build.sh $system"
    sbatch -p "$queue_group" -N "$build_nodes" -t "$elapse" --ntasks-per-node=1 --cpus-per-task="$build_cpus_per_task" \
      --wrap="bash programs/${code}/build.sh $system"
    ;;
  *)
    echo "Error: test_submit_build.sh currently supports RC systems only: RC_GH200, RC_DGXSP, RC_GENOA"
    echo "Selected system: $system"
    exit 1
    ;;
esac
