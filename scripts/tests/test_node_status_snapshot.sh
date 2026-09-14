#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping node status snapshot test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/unknown/results"
pushd "${TMP_DIR}/unknown" >/dev/null
BK_NODE_STATUS_SNAPSHOT_REMOTE=0 \
  bash "${REPO_DIR}/scripts/collect_node_status_snapshot.sh" results/node_status_snapshot_run.json >/dev/null
jq -e '
  .schema_version == 1 and
  .kind == "node_status_snapshot" and
  .collection_status == "unsupported" and
  .scheduler.kind == "unknown" and
  .summary.observed_host_count == 1 and
  (.summary.gpu_query_statuses | type) == "array"
' results/node_status_snapshot_run.json >/dev/null
popd >/dev/null

mkdir -p "${TMP_DIR}/slurm/results" "${TMP_DIR}/bin"

cat > "${TMP_DIR}/bin/hostname" <<'EOF'
#!/bin/bash
printf '%s\n' "${BK_TEST_HOSTNAME:-node-a}"
EOF

cat > "${TMP_DIR}/bin/scontrol" <<'EOF'
#!/bin/bash
set -euo pipefail
if [ "${1:-}" = "show" ] && [ "${2:-}" = "hostnames" ]; then
  printf '%s\n' node-a node-b
  exit 0
fi
exit 1
EOF

cat > "${TMP_DIR}/bin/srun" <<'EOF'
#!/bin/bash
set -euo pipefail
while [ "$#" -gt 0 ]; do
  case "$1" in
    -N|-n|--nodes|--ntasks|--ntasks-per-node)
      shift 2
      ;;
    --nodes=*|--ntasks=*|--ntasks-per-node=*)
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      shift
      ;;
    *)
      break
      ;;
  esac
done
BK_TEST_HOSTNAME=node-a "$@"
BK_TEST_HOSTNAME=node-b "$@"
EOF

cat > "${TMP_DIR}/bin/nvidia-smi" <<'EOF'
#!/bin/bash
set -euo pipefail
case "$*" in
  *--query-gpu=*)
    if [ "${BK_TEST_HOSTNAME:-node-a}" = "node-b" ]; then
      printf '%s\n' \
        "0, NVIDIA B200, 128, 183000, 0, 35, 1230, 2000, P0" \
        "1, NVIDIA B200, 256, 183000, 0, 36, 1230, 2000, P0"
    else
      printf '%s\n' \
        "0, NVIDIA B200, 0, 183000, 0, 33, 1230, 2000, P0" \
        "1, NVIDIA B200, 0, 183000, 0, 34, 1230, 2000, P0"
    fi
    ;;
  *--query-compute-apps=*)
    if [ "${BK_TEST_HOSTNAME:-node-a}" = "node-b" ]; then
      printf '%s\n' "1234, 512"
    fi
    ;;
  *)
    exit 1
    ;;
esac
EOF

chmod +x "${TMP_DIR}/bin/hostname" "${TMP_DIR}/bin/scontrol" "${TMP_DIR}/bin/srun" "${TMP_DIR}/bin/nvidia-smi"

pushd "${TMP_DIR}/slurm" >/dev/null
PATH="${TMP_DIR}/bin:${PATH}" \
SLURM_JOB_ID=123 \
SLURM_JOB_PARTITION=gpu \
SLURM_JOB_NODELIST="node-[a-b]" \
SLURM_JOB_NUM_NODES=2 \
SLURM_NTASKS=4 \
SLURM_TASKS_PER_NODE="2(x2)" \
SLURM_CPUS_PER_TASK=32 \
SLURM_JOB_GPUS="0,1,2,3" \
BK_NODE_STATUS_SNAPSHOT_TIMEOUT_SECONDS=5 \
  bash "${REPO_DIR}/scripts/collect_node_status_snapshot.sh" results/node_status_snapshot_run.json >/dev/null

jq -e '
  .schema_version == 1 and
  .kind == "node_status_snapshot" and
  .collection_status == "ok" and
  .scheduler.kind == "slurm" and
  .scheduler.slurm.remote_collection_status == "ok" and
  .allocation.scheduler_hosts == ["node-a", "node-b"] and
  (.observed.hosts | length) == 2 and
  .summary.scheduler_host_count == 2 and
  .summary.observed_host_count == 2 and
  .summary.observed_gpu_count == 4 and
  .summary.gpu_memory_used_total_mib == 384 and
  .summary.gpu_compute_process_count == 1 and
  .summary.gpu_compute_memory_used_mib == 512 and
  (.summary.warnings | index("gpu_compute_processes_present_before_run") != null)
' results/node_status_snapshot_run.json >/dev/null

if jq -e 'tostring | contains("1234")' results/node_status_snapshot_run.json >/dev/null; then
  echo "node status snapshot should not record process identifiers" >&2
  exit 1
fi
popd >/dev/null

echo "node status snapshot test passed"
