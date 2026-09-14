#!/bin/bash
set -euo pipefail

out_file="${1:-results/node_status_snapshot_run.json}"
snapshot_stage="${BK_NODE_STATUS_SNAPSHOT_STAGE:-run}"
script_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

json_string_array() {
  jq -R -s -c 'split("\n") | map(select(length > 0))'
}

json_lines_to_array() {
  jq -s -c 'unique_by(.hostname // "")'
}

detect_scheduler_kind() {
  if [ -n "${SLURM_JOB_ID:-}" ] || [ -n "${SLURM_JOBID:-}" ]; then
    printf '%s\n' "slurm"
  elif [ -n "${PJM_JOBID:-}" ] || [ -n "${PJM_JOB_ID:-}" ]; then
    printf '%s\n' "pjm"
  elif [ -n "${PBS_JOBID:-}" ]; then
    printf '%s\n' "pbs"
  else
    printf '%s\n' "unknown"
  fi
}

collect_scheduler_hosts() {
  local kind="$1"
  local nodelist=""
  local nodefile=""

  case "$kind" in
    slurm)
      nodelist="${SLURM_JOB_NODELIST:-${SLURM_NODELIST:-}}"
      if [ -n "$nodelist" ] && command -v scontrol >/dev/null 2>&1; then
        scontrol show hostnames "$nodelist" 2>/dev/null || true
      elif [ -n "$nodelist" ]; then
        printf '%s\n' "$nodelist"
      fi
      ;;
    pbs)
      nodefile="${PBS_NODEFILE:-}"
      if [ -n "$nodefile" ] && [ -r "$nodefile" ]; then
        awk 'NF {print $1}' "$nodefile" | sort -u
      fi
      ;;
    pjm)
      nodefile="${PJM_NODEINF:-${PJM_O_NODEINF:-}}"
      if [ -n "$nodefile" ] && [ -r "$nodefile" ]; then
        awk 'NF {print $1}' "$nodefile" | sort -u
      elif [ -n "${PJM_NODE:-}" ]; then
        printf '%s\n' "${PJM_NODE}" | tr ',' '\n'
      fi
      ;;
  esac
}

trimmed_number_or_zero() {
  awk '
    {
      value = $0
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if (value ~ /^[0-9]+$/) {
        total += value
      }
    }
    END { print total + 0 }
  '
}

count_compute_app_rows() {
  awk -F, '
    {
      pid = $1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", pid)
      if (pid ~ /^[0-9]+$/) {
        count += 1
      }
    }
    END {print count + 0}
  '
}

collect_gpu_state_json() {
  local gpu_csv=""
  local gpus_json="[]"
  local gpu_query_status="unavailable"
  local compute_apps_csv=""
  local compute_process_count=0
  local compute_memory_used_mib=0

  if command -v nvidia-smi >/dev/null 2>&1; then
    if gpu_csv=$(nvidia-smi \
      --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu,clocks.sm,clocks.mem,pstate \
      --format=csv,noheader,nounits 2>/dev/null); then
      gpu_query_status="ok"
      gpus_json=$(printf '%s\n' "$gpu_csv" | jq -R -s -c '
        def trim: sub("^[[:space:]]+"; "") | sub("[[:space:]]+$"; "");
        def maybe_number: tonumber? // null;
        split("\n")
        | map(select(length > 0))
        | map(
            split(",")
            | map(trim)
            | {
                index: (.[0] // ""),
                name: (.[1] // ""),
                memory_used_mib: ((.[2] // "") | maybe_number),
                memory_total_mib: ((.[3] // "") | maybe_number),
                utilization_gpu_percent: ((.[4] // "") | maybe_number),
                temperature_c: ((.[5] // "") | maybe_number),
                clocks_sm_mhz: ((.[6] // "") | maybe_number),
                clocks_mem_mhz: ((.[7] // "") | maybe_number),
                pstate: (.[8] // "")
              }
          )
      ')
    else
      gpu_query_status="failed"
    fi

    compute_apps_csv=$(nvidia-smi \
      --query-compute-apps=pid,used_memory \
      --format=csv,noheader,nounits 2>/dev/null || true)
    compute_process_count=$(printf '%s\n' "$compute_apps_csv" | count_compute_app_rows)
    compute_memory_used_mib=$(
      printf '%s\n' "$compute_apps_csv" \
        | awk -F, '{print $2}' \
        | trimmed_number_or_zero
    )
  fi

  jq -n -c \
    --arg query_status "$gpu_query_status" \
    --argjson gpus "$gpus_json" \
    --argjson compute_process_count "$compute_process_count" \
    --argjson compute_memory_used_mib "$compute_memory_used_mib" \
    '{
      available: ($query_status == "ok"),
      query_status: $query_status,
      gpus: $gpus,
      process_summary: {
        compute_process_count: $compute_process_count,
        memory_used_mib: $compute_memory_used_mib
      }
    }'
}

collect_host_state_json() {
  local cpu_logical_count=""
  local memory_total_kib=""
  local memory_available_kib=""
  local load_average_1m=""
  local load_average_5m=""
  local load_average_15m=""

  cpu_logical_count=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || true)
  if [ -r /proc/meminfo ]; then
    memory_total_kib=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)
    memory_available_kib=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo)
  fi
  if [ -r /proc/loadavg ]; then
    read -r load_average_1m load_average_5m load_average_15m _ < /proc/loadavg || true
  fi

  jq -n -c \
    --arg cpu_logical_count "$cpu_logical_count" \
    --arg memory_total_kib "$memory_total_kib" \
    --arg memory_available_kib "$memory_available_kib" \
    --arg load_average_1m "$load_average_1m" \
    --arg load_average_5m "$load_average_5m" \
    --arg load_average_15m "$load_average_15m" \
    '{
      cpu_logical_count: ($cpu_logical_count | tonumber?),
      memory_total_mib: (($memory_total_kib | tonumber?) as $v | if $v == null then null else $v / 1024 end),
      memory_available_mib: (($memory_available_kib | tonumber?) as $v | if $v == null then null else $v / 1024 end),
      load_average: {
        one_minute: ($load_average_1m | tonumber?),
        five_minutes: ($load_average_5m | tonumber?),
        fifteen_minutes: ($load_average_15m | tonumber?)
      }
    }'
}

collect_worker_json() {
  local hostname_value=""
  local host_state_json="{}"
  local gpu_state_json="{}"

  hostname_value=$(hostname 2>/dev/null || printf '%s' "")
  host_state_json=$(collect_host_state_json)
  gpu_state_json=$(collect_gpu_state_json)

  jq -n -c \
    --arg hostname "$hostname_value" \
    --arg scheduler_kind "$(detect_scheduler_kind)" \
    --arg slurm_procid "${SLURM_PROCID:-}" \
    --arg slurm_localid "${SLURM_LOCALID:-}" \
    --arg ompi_rank "${OMPI_COMM_WORLD_RANK:-}" \
    --arg ompi_local_rank "${OMPI_COMM_WORLD_LOCAL_RANK:-}" \
    --arg cuda_visible_devices "${CUDA_VISIBLE_DEVICES:-}" \
    --argjson host_state "$host_state_json" \
    --argjson gpu_state "$gpu_state_json" \
    '{
      hostname: $hostname,
      scheduler_kind: $scheduler_kind,
      host_state: $host_state,
      rank_environment: {
        slurm_procid: $slurm_procid,
        slurm_localid: $slurm_localid,
        ompi_rank: $ompi_rank,
        ompi_local_rank: $ompi_local_rank,
        cuda_visible_devices: $cuda_visible_devices
      },
      gpu_state: $gpu_state
    }'
}

remote_snapshot_enabled() {
  case "${BK_NODE_STATUS_SNAPSHOT_REMOTE:-auto}" in
    0|false|False|FALSE|no|No|NO|off|Off|OFF)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

collect_slurm_remote_workers() {
  local scheduler_host_count="$1"
  local timeout_seconds="${BK_NODE_STATUS_SNAPSHOT_TIMEOUT_SECONDS:-20}"
  local stdout_file=""
  local stderr_file=""
  local status=0

  if ! remote_snapshot_enabled; then
    return 1
  fi
  if [ "$scheduler_host_count" -le 1 ]; then
    return 1
  fi
  if ! command -v srun >/dev/null 2>&1; then
    return 1
  fi

  stdout_file=$(mktemp)
  stderr_file=$(mktemp)
  if command -v timeout >/dev/null 2>&1; then
    timeout "${timeout_seconds}s" srun -N "$scheduler_host_count" -n "$scheduler_host_count" \
      --ntasks-per-node=1 bash "$script_path" --worker >"$stdout_file" 2>"$stderr_file" || status=$?
  else
    srun -N "$scheduler_host_count" -n "$scheduler_host_count" \
      --ntasks-per-node=1 bash "$script_path" --worker >"$stdout_file" 2>"$stderr_file" || status=$?
  fi

  rm -f "$stderr_file"
  if [ "$status" -ne 0 ]; then
    rm -f "$stdout_file"
    return 1
  fi

  awk '/^[[:space:]]*\{/ {print}' "$stdout_file"
  rm -f "$stdout_file"
}

build_summary_json() {
  local scheduler_hosts_json="$1"
  local hosts_json="$2"

  jq -n -c \
    --argjson scheduler_hosts "$scheduler_hosts_json" \
    --argjson hosts "$hosts_json" \
    '
    ($hosts | map(.gpu_state.gpus // []) | add // []) as $gpus
    | ($hosts | map(.gpu_state.process_summary.compute_process_count // 0) | add // 0) as $process_count
    | ($hosts | map(.gpu_state.process_summary.memory_used_mib // 0) | add // 0) as $process_memory
    | ($gpus | map(.memory_used_mib // 0) | add // 0) as $gpu_memory
    | ($hosts | map(.host_state.cpu_logical_count) | map(select(. != null)) | unique) as $cpu_counts
    | ($hosts | map(.host_state.memory_total_mib) | map(select(. != null)) | unique) as $memory_totals
    | ($hosts | map(.host_state.memory_available_mib) | map(select(. != null))) as $memory_available
    | ($hosts | map(.host_state.load_average.one_minute) | map(select(. != null))) as $load_1m
    | ($hosts | map(.host_state.load_average.five_minutes) | map(select(. != null))) as $load_5m
    | {
        scheduler_host_count: ($scheduler_hosts | length),
        observed_host_count: ($hosts | length),
        cpu_logical_counts: $cpu_counts,
        memory_total_mib_min: ($memory_totals | min),
        memory_total_mib_max: ($memory_totals | max),
        memory_available_mib_min: ($memory_available | min),
        load_average_1m_max: ($load_1m | max),
        load_average_5m_max: ($load_5m | max),
        observed_gpu_count: ($gpus | length),
        gpu_memory_used_total_mib: $gpu_memory,
        gpu_compute_process_count: $process_count,
        gpu_compute_memory_used_mib: $process_memory,
        gpu_query_statuses: ($hosts | map(.gpu_state.query_status // "unknown") | unique),
        warnings: (
          []
          + (if (($scheduler_hosts | length) > 0 and ($hosts | length) != ($scheduler_hosts | length))
             then ["observed_host_count_differs_from_scheduler_host_count"] else [] end)
          + (if ($cpu_counts | length) > 1
             then ["cpu_count_differs_across_observed_hosts"] else [] end)
          + (if ($memory_totals | length) > 1
             then ["memory_total_differs_across_observed_hosts"] else [] end)
          + (if $process_count > 0
             then ["gpu_compute_processes_present_before_run"] else [] end)
        )
      }'
}

if [ "${1:-}" = "--worker" ]; then
  collect_worker_json
  exit 0
fi

mkdir -p "$(dirname "$out_file")"

scheduler_kind=$(detect_scheduler_kind)
scheduler_hosts_json=$(collect_scheduler_hosts "$scheduler_kind" | json_string_array)
scheduler_host_count=$(printf '%s' "$scheduler_hosts_json" | jq 'length')
collection_status="ok"
remote_collection_status="not_attempted"
collection_warnings_json="[]"

worker_lines=""
if [ "$scheduler_kind" = "slurm" ]; then
  if worker_lines=$(collect_slurm_remote_workers "$scheduler_host_count"); then
    remote_collection_status="ok"
  elif [ "$scheduler_host_count" -gt 1 ] && remote_snapshot_enabled; then
    remote_collection_status="failed"
    collection_status="partial"
    collection_warnings_json='["slurm_remote_collection_failed"]'
  fi
fi

if [ -z "$worker_lines" ]; then
  worker_lines=$(collect_worker_json)
fi

if ! hosts_json=$(printf '%s\n' "$worker_lines" | json_lines_to_array 2>/dev/null); then
  hosts_json=$(collect_worker_json | json_lines_to_array)
  collection_status="partial"
  collection_warnings_json='["worker_output_parse_failed"]'
fi

if [ "$scheduler_kind" = "unknown" ]; then
  collection_status="unsupported"
fi

summary_json=$(build_summary_json "$scheduler_hosts_json" "$hosts_json")

jq -n \
  --argjson schema_version 1 \
  --arg kind "node_status_snapshot" \
  --arg stage "$snapshot_stage" \
  --arg collected_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg collection_status "$collection_status" \
  --arg remote_collection_status "$remote_collection_status" \
  --arg scheduler_kind "$scheduler_kind" \
  --arg slurm_job_id "${SLURM_JOB_ID:-${SLURM_JOBID:-}}" \
  --arg slurm_partition "${SLURM_JOB_PARTITION:-}" \
  --arg slurm_job_nodelist "${SLURM_JOB_NODELIST:-${SLURM_NODELIST:-}}" \
  --arg slurm_job_num_nodes "${SLURM_JOB_NUM_NODES:-${SLURM_NNODES:-}}" \
  --arg slurm_ntasks "${SLURM_NTASKS:-}" \
  --arg slurm_tasks_per_node "${SLURM_TASKS_PER_NODE:-}" \
  --arg slurm_cpus_per_task "${SLURM_CPUS_PER_TASK:-}" \
  --arg slurm_job_gpus "${SLURM_JOB_GPUS:-}" \
  --arg slurm_gpus_on_node "${SLURM_GPUS_ON_NODE:-}" \
  --arg slurm_gpus_per_node "${SLURM_GPUS_PER_NODE:-}" \
  --arg slurm_gpus_per_task "${SLURM_GPUS_PER_TASK:-}" \
  --arg pbs_jobid "${PBS_JOBID:-}" \
  --arg pbs_nodefile "${PBS_NODEFILE:-}" \
  --arg pjm_jobid "${PJM_JOBID:-${PJM_JOB_ID:-}}" \
  --arg pjm_nodeinf "${PJM_NODEINF:-${PJM_O_NODEINF:-}}" \
  --argjson scheduler_hosts "$scheduler_hosts_json" \
  --argjson observed_hosts "$hosts_json" \
  --argjson summary "$summary_json" \
  --argjson collection_warnings "$collection_warnings_json" \
  '{
    schema_version: $schema_version,
    kind: $kind,
    stage: $stage,
    collected_at: $collected_at,
    collection_status: $collection_status,
    collection_warnings: $collection_warnings,
    scheduler: {
      kind: $scheduler_kind,
      slurm: {
        job_id: $slurm_job_id,
        partition: $slurm_partition,
        job_nodelist: $slurm_job_nodelist,
        job_num_nodes: $slurm_job_num_nodes,
        ntasks: $slurm_ntasks,
        tasks_per_node: $slurm_tasks_per_node,
        cpus_per_task: $slurm_cpus_per_task,
        job_gpus: $slurm_job_gpus,
        gpus_on_node: $slurm_gpus_on_node,
        gpus_per_node: $slurm_gpus_per_node,
        gpus_per_task: $slurm_gpus_per_task,
        remote_collection_status: $remote_collection_status
      },
      pbs: {
        job_id: $pbs_jobid,
        nodefile: $pbs_nodefile
      },
      pjm: {
        job_id: $pjm_jobid,
        nodeinf: $pjm_nodeinf
      }
    },
    allocation: {
      scheduler_hosts: $scheduler_hosts
    },
    observed: {
      hosts: $observed_hosts
    },
    summary: $summary
  }' > "$out_file"

echo "Wrote node status snapshot: $out_file"
