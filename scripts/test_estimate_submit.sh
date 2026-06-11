#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/test_estimate_submit.sh <code> <line_number>
  scripts/test_estimate_submit.sh <code> <line_number> --estimate-only

The first form submits a local scheduler job that runs the benchmark with
GPU-MLP profiler settings and creates results/result*.json.  The second form
runs the estimation step from the existing results directory.  When SIF or
BK_ESTIMATE_APPTAINER_IMAGE is set, --estimate-only runs inside Apptainer.
EOF
}

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  usage
  exit 1
fi

code="$1"
list_csv_line_num="$2"
mode="${3:-submit}"

if ! [[ "$list_csv_line_num" =~ ^[0-9]+$ ]] || [ "$list_csv_line_num" -le 0 ]; then
  echo "Error: <line_number> must be a positive integer" >&2
  exit 1
fi

source ./scripts/job_functions.sh

list_file="programs/${code}/list.csv"
if [ ! -f "$list_file" ]; then
  echo "Error: $list_file does not exist" >&2
  exit 1
fi

line=$(tail -n +2 "$list_file" | sed -n "${list_csv_line_num}p")
if [ -z "$line" ]; then
  echo "Error: line $list_csv_line_num does not exist in $list_file" >&2
  exit 1
fi

IFS=, read -r -a cols <<< "$line"
system="${cols[0]}"
enable="${cols[1]}"
nodes="${cols[2]}"
numproc_node="${cols[3]}"
nthreads="${cols[4]}"
elapse="${cols[5]}"

if [[ "$enable" != "yes" ]]; then
  echo "Error: selected line is disabled: $line" >&2
  exit 1
fi

if [[ "$mode" == "--estimate-only" ]]; then
  export BK_GPU_MLP_PERFTOOLS_ROOT="${BK_GPU_MLP_PERFTOOLS_ROOT:-${PERFTOOLS:-}}"
  image="${BK_ESTIMATE_APPTAINER_IMAGE:-${SIF:-}}"
  if [[ -n "$image" ]]; then
    binds="${PWD}:${PWD},/tmp:/tmp"
    if [[ -n "${BK_GPU_MLP_PERFTOOLS_ROOT:-}" ]]; then
      binds="${binds},${BK_GPU_MLP_PERFTOOLS_ROOT}:${BK_GPU_MLP_PERFTOOLS_ROOT}"
    fi
    apptainer exec --bind "$binds" --pwd "$PWD" "$image" \
      bash scripts/estimation/run.sh "$code"
  else
    bash scripts/estimation/run.sh "$code"
  fi
  exit 0
fi

if [[ "$mode" != "submit" ]]; then
  usage
  exit 1
fi

echo "Selected estimation test configuration:"
echo "  code=$code"
echo "  line=$list_csv_line_num"
echo "  system=$system nodes=$nodes numproc_node=$numproc_node nthreads=$nthreads elapse=$elapse"

cat > script.estimate.sh <<EOF
#!/bin/bash
set -euo pipefail
cd "$PWD"

rm -rf results
mkdir -p results

export BK_GENESIS_GPU_MLP_PROFILE="\${BK_GENESIS_GPU_MLP_PROFILE:-true}"
export BK_GPU_MLP_NCU_LAUNCH_COUNT="\${BK_GPU_MLP_NCU_LAUNCH_COUNT:-20}"
export BK_GPU_MLP_SOURCE_GPU="\${BK_GPU_MLP_SOURCE_GPU:-H100}"
export BK_GPU_MLP_KERNEL_COUNT="\${BK_GPU_MLP_KERNEL_COUNT:-20}"

bash programs/${code}/run.sh ${system} ${nodes} ${numproc_node} ${nthreads}
bash scripts/result.sh ${code} ${system} local-estimate "" test_estimate_submit ""
EOF

chmod +x script.estimate.sh

case "$system" in
  MiyabiG)
    group_name=$(groups | awk '{print $2}')
    echo qsub -q debug-g -l select=${nodes}:mpiprocs=${numproc_node}:ompthreads=${nthreads} -l walltime=${elapse} -W group_list=${group_name} script.estimate.sh
    qsub -q debug-g -l select=${nodes}:mpiprocs=${numproc_node}:ompthreads=${nthreads} -l walltime=${elapse} -W group_list=${group_name} script.estimate.sh
    ;;
  RC_GH200)
    echo sbatch -p qc-gh200 -N "${nodes}" -t "${elapse}" --ntasks-per-node="${numproc_node}" --cpus-per-task="${nthreads}" --wrap="bash script.estimate.sh"
    sbatch -p qc-gh200 -N "${nodes}" -t "${elapse}" --ntasks-per-node="${numproc_node}" --cpus-per-task="${nthreads}" --wrap="bash script.estimate.sh"
    ;;
  *)
    echo "Error: test_estimate_submit currently supports MiyabiG and RC_GH200, got ${system}" >&2
    exit 1
    ;;
esac

cat <<EOF

After the scheduler job finishes, run:

  scripts/test_estimate_submit.sh ${code} ${list_csv_line_num} --estimate-only

Set SIF or BK_ESTIMATE_APPTAINER_IMAGE to run the estimate step in Apptainer.
Set PERFTOOLS or BK_GPU_MLP_PERFTOOLS_ROOT to the PerfTools checkout.
EOF
