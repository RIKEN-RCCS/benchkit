#!/bin/bash
set -euo pipefail

# Capture on allocated hosts; interpretation and summaries run in send_results.
# shellcheck source=scripts/json_output.sh
source "$(dirname "${BASH_SOURCE[0]}")/json_output.sh"
script_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

detect_scheduler_kind() {
  if [ -n "${SLURM_JOB_ID:-${SLURM_JOBID:-}}" ]; then
    printf slurm
  elif [ -n "${PJM_JOBID:-${PJM_JOB_ID:-}}" ]; then
    printf pjm
  elif [ -n "${PBS_JOBID:-}" ]; then
    printf pbs
  else
    printf unknown
  fi
}

collect_scheduler_hosts() {
  local nodefile="" nodelist=""
  case "$1" in
    slurm)
      nodelist="${SLURM_JOB_NODELIST:-${SLURM_NODELIST:-}}"
      if [ -n "$nodelist" ] && command -v scontrol >/dev/null 2>&1; then
        scontrol show hostnames "$nodelist" 2>/dev/null || true
      elif [ -n "$nodelist" ]; then
        printf '%s\n' "$nodelist"
      fi ;;
    pbs|pjm)
      if [ "$1" = pbs ]; then
        nodefile="${PBS_NODEFILE:-}"
      else
        nodefile="${PJM_NODEINF:-${PJM_O_NODEINF:-}}"
      fi
      if [ -n "$nodefile" ] && [ -r "$nodefile" ]; then
        awk 'NF {print $1}' "$nodefile" | sort -u
      elif [ "$1" = pjm ] && [ -n "${PJM_NODE:-}" ]; then
        printf '%s\n' "$PJM_NODE" | tr ',' '\n'
      fi ;;
  esac
}

collect_worker() {
  local total="" available="" load1="" load5="" load15=""
  local gpu_csv="" gpu_status=unavailable process_counts='0 0' processes memory
  if [ -r /proc/meminfo ]; then
    total=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)
    available=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo)
  fi
  if [ -r /proc/loadavg ]; then
    read -r load1 load5 load15 _ < /proc/loadavg || true
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    if gpu_csv=$(nvidia-smi \
        --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu,clocks.sm,clocks.mem,pstate \
        --format=csv,noheader,nounits 2>/dev/null); then
      gpu_status=ok
    else
      gpu_status=failed
    fi
    # Preserve aggregate counts only, never process identities or command lines.
    process_counts=$({ nvidia-smi --query-compute-apps=pid,used_memory \
        --format=csv,noheader,nounits 2>/dev/null || true; } | awk -F, '
      {gsub(/[[:space:]]/, "", $1); gsub(/[[:space:]]/, "", $2)
       if ($1 ~ /^[0-9]+$/) count++
       if ($2 ~ /^[0-9]+$/) memory += $2}
      END {print count+0, memory+0}')
  fi
  read -r processes memory <<< "$process_counts"
  bk_json_object string hostname "$(hostname 2>/dev/null || true)" \
    string scheduler_kind "$(detect_scheduler_kind)" \
    json rank_environment "$(bk_json_object \
      string slurm_procid "${SLURM_PROCID:-}" string slurm_localid "${SLURM_LOCALID:-}" \
      string ompi_rank "${OMPI_COMM_WORLD_RANK:-}" string ompi_local_rank "${OMPI_COMM_WORLD_LOCAL_RANK:-}" \
      string cuda_visible_devices "${CUDA_VISIBLE_DEVICES:-}")" \
    json host_fields "$(bk_json_object \
      string cpu_logical_count "$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || true)" \
      string memory_total_kib "$total" string memory_available_kib "$available" \
      string load1 "$load1" string load5 "$load5" string load15 "$load15")" \
    json gpu_fields "$(bk_json_object string query_status "$gpu_status" string csv "$gpu_csv" \
      string compute_process_count "$processes" string memory_used_mib "$memory")"
}

if [ "${1:-}" = --worker ]; then
  collect_worker
  exit 0
fi

out_file="${1:-results/node_status_snapshot_run.json}"
mkdir -p "$(dirname "$out_file")"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
kind=$(detect_scheduler_kind)
collect_scheduler_hosts "$kind" > "$work/hosts"
host_count=$(awk 'NF {n++} END {print n+0}' "$work/hosts")
status=ok
remote_status=not_attempted
warnings='[]'
remote_enabled=true
case "${BK_NODE_STATUS_SNAPSHOT_REMOTE:-auto}" in
  0|false|False|FALSE|no|No|NO|off|Off|OFF) remote_enabled=false ;;
esac
if [ "$kind" = slurm ] && [ "$host_count" -gt 1 ] && [ "$remote_enabled" = true ]; then
  remote_status=failed
  if command -v srun >/dev/null 2>&1; then
    command=(srun -N "$host_count" -n "$host_count" --ntasks-per-node=1 bash "$script_path" --worker)
    if command -v timeout >/dev/null 2>&1; then
      command=(timeout "${BK_NODE_STATUS_SNAPSHOT_TIMEOUT_SECONDS:-20}s" "${command[@]}")
    fi
    if "${command[@]}" > "$work/workers" 2> "$work/errors"; then
      remote_status=ok
    fi
  fi
  if [ "$remote_status" = failed ]; then
    status=partial
    warnings='["slurm_remote_collection_failed"]'
  fi
fi
# Keep local evidence even when remote workers fail or produce malformed output.
collect_worker > "$work/local"
[ "$kind" != unknown ] || status=unsupported
bk_json_object string record_format node-status-capture-v1 \
  json schema_version 1 string kind node_status_snapshot \
  string stage "${BK_NODE_STATUS_SNAPSHOT_STAGE:-run}" \
  string collected_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  string collection_status "$status" json collection_warnings "$warnings" \
  json scheduler "$(bk_json_object string kind "$kind" \
    json slurm "$(bk_json_object \
      string job_id "${SLURM_JOB_ID:-${SLURM_JOBID:-}}" string partition "${SLURM_JOB_PARTITION:-}" \
      string job_nodelist "${SLURM_JOB_NODELIST:-${SLURM_NODELIST:-}}" \
      string job_num_nodes "${SLURM_JOB_NUM_NODES:-${SLURM_NNODES:-}}" \
      string ntasks "${SLURM_NTASKS:-}" string tasks_per_node "${SLURM_TASKS_PER_NODE:-}" \
      string cpus_per_task "${SLURM_CPUS_PER_TASK:-}" string job_gpus "${SLURM_JOB_GPUS:-}" \
      string gpus_on_node "${SLURM_GPUS_ON_NODE:-}" string gpus_per_node "${SLURM_GPUS_PER_NODE:-}" \
      string gpus_per_task "${SLURM_GPUS_PER_TASK:-}" string remote_collection_status "$remote_status")" \
    json pbs "$(bk_json_object string job_id "${PBS_JOBID:-}" string nodefile "${PBS_NODEFILE:-}")" \
    json pjm "$(bk_json_object string job_id "${PJM_JOBID:-${PJM_JOB_ID:-}}" \
      string nodeinf "${PJM_NODEINF:-${PJM_O_NODEINF:-}}")")" \
  json allocation "$(bk_json_object json scheduler_hosts "$(bk_json_lines_array < "$work/hosts")")" \
  string local_worker "$(< "$work/local")" \
  string remote_workers "$(if [ "$remote_status" = ok ]; then cat "$work/workers"; fi)" \
  > "${out_file}.capture"
echo "Wrote node status capture: ${out_file}.capture"
