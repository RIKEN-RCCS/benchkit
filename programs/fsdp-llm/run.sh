#!/bin/bash
set -euo pipefail

system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
n_ranks=$((nodes * numproc_node))

source scripts/bk_functions.sh

ARTIFACT_DIR="${PWD}/artifacts"
RESULTS_DIR="${PWD}/results"
mkdir -p "${RESULTS_DIR}"
: > "${RESULTS_DIR}/result"
export OMP_NUM_THREADS="${nthreads}" NNODES="${nodes}" TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

# What each row trains, one "model tp micro-batch" per run (README, "Parameter choices"): the 1B
# wherever it fits, the 30B wherever it fits. tp is the tensor-parallel size (1: FSDP2 only); the micro-batch
# is sequences per tensor-parallel group per step, the largest that fits or near it.
case "${system}" in
  RIKYU) RUNS=("1b 1 16" "30b 4 64"); dtype=bf16 ;;
  RC_DGXSP) RUNS=("1b 1 16"); dtype=bf16 ;;
  # The 30B fits Genoa's 768 GB but takes an hour a row at 13 tokens/s (README, "Results").
  RC_GENOA) RUNS=("1b 1 4"); dtype=fp32 ;;
  # 30B needs about 64 nodes of A64FX memory.
  Fugaku) if (( nodes >= 64 )); then RUNS=("30b 4 1"); else RUNS=("1b 4 4"); fi; dtype=fp32 ;;
  *) echo "Unknown system: ${system}" >&2; exit 1 ;;
esac

train() {  # train <logfile> <llm_train.py arguments...>: launch on this system; returns its exit code
  local log="$1"; shift
  case "${system}" in
    RIKYU)
      module load cuda/13.2.2
      # One torch.distributed.run agent per node, with the CPUs of all its workers: --ntasks pins
      # one task per node in a 4-tasks-per-node allocation, which would otherwise inherit one
      # task's --cpus-per-task.
      MASTER_ADDR=$(scontrol show hostnames "${SLURM_JOB_NODELIST}" | head -n 1)
      srun --ntasks="${nodes}" --ntasks-per-node=1 --cpus-per-task=$((numproc_node * nthreads)) \
        "${ARTIFACT_DIR}/venv/bin/python" -m torch.distributed.run --nnodes="${nodes}" \
        --nproc_per_node="${numproc_node}" --rdzv_backend=c10d --rdzv_endpoint="${MASTER_ADDR}:29500" \
        "${ARTIFACT_DIR}/llm_train.py" "$@" --backend nccl > "${log}" 2>&1
      ;;
    RC_DGXSP)
      # Unified memory: expandable segments keep the allocator from fragmenting it.
      PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True "${ARTIFACT_DIR}/venv/bin/python" -m torch.distributed.run --standalone \
        --nproc_per_node="${numproc_node}" "${ARTIFACT_DIR}/llm_train.py" "$@" --backend nccl > "${log}" 2>&1
      ;;
    RC_GENOA)
      "${ARTIFACT_DIR}/venv/bin/python" -m torch.distributed.run --standalone --nproc_per_node="${numproc_node}" \
        "${ARTIFACT_DIR}/llm_train.py" "$@" --backend gloo > "${log}" 2>&1
      ;;
    Fugaku)
      # pytorch-fugaku's launch: pf-setup collects the compute node's Tofu libraries and the
      # process-group settings; one pf-run container per rank under Fujitsu mpiexec, collectives
      # over Fujitsu MPI (torch_fugaku's "fjmpi" backend, rendezvous over MPI). Rank 0 logs.
      export PF_DIR="${ARTIFACT_DIR}/pytorch-fugaku/fugaku" SIF log LLM_ARGS="$* --backend fjmpi"
      mpiexec -n "${n_ranks}" bash -c '
        out=/dev/null; [[ ${PMIX_RANK} -eq 0 ]] && out="${log}"
        exec "${PF_DIR}/pf-run" "${SIF}" python /work/artifacts/llm_train.py ${LLM_ARGS} > "${out}" 2>&1'
      ;;
  esac
}

if [[ "${system}" == Fugaku ]]; then
  SIF="${BK_FSDP_LLM_SIF:-${ARTIFACT_DIR}/pytorch-fugaku-d7fb755.sif}"
  export PF_HOSTLIB="${PWD}/.pf-hostlib" PF_BIND="${PWD}:/work:rw"
  # torch's bundled mimalloc otherwise keeps freed memory: peak per rank 5.8 -> 3.8 GB at 30B.
  export SINGULARITYENV_MIMALLOC_PURGE_DELAY=0
  # The SIF's SHA-256 goes into the run's environment snapshot; a slow read does not block training.
  if [[ -f "${RESULTS_DIR}/environment_snapshot_run.json" ]]; then
    timeout --kill-after=2 120 python3 "${BK_BENCHKIT_ROOT}/scripts/record_runtime_image.py" \
      "${SIF}" "${RESULTS_DIR}/environment_snapshot_run.json" || echo "fsdp-llm: SIF observation unavailable" >&2
  fi
  "${ARTIFACT_DIR}/pytorch-fugaku/fugaku/pf-setup" "${numproc_node}"
fi

failed=0
for run in "${RUNS[@]}"; do
  read -r model tp mb <<< "${run}"
  logfile="${PWD}/train-${model}.log"
  # Sequence 2048, sequence parallel (with tp > 1) and activation checkpointing; five steps, the
  # first two excluded.
  status=0
  train "${logfile}" --model "${model}" --tp "${tp}" --micro-batch "${mb}" --dtype "${dtype}" \
    --seq 2048 --sp --checkpointing --steps 5 --warmup 2 || status=$?
  # Require both a clean launcher exit and the application-level checks (the FOM line, and a
  # final loss that is finite and near ln(vocab) + logit variance, 11.8-12.2 here): a crashed
  # rank can still let the launcher exit 0, so the log content alone is not proof of success.
  read -r fom <<< "$(python3 - "${logfile}" <<'PY'
import json, math, sys
fom, last = None, None
for line in open(sys.argv[1], errors="replace"):
    if line.startswith('{"event"'):
        e = json.loads(line)
        if e["event"] == "fom":
            fom = e
        elif e["event"] == "step":
            last = e["loss"]
ok = fom is not None and last is not None and math.isfinite(last) and 9.0 < last < 14.0
print(fom["tokens_per_s"] if ok else "-")
PY
)"
  cp "${logfile}" "${RESULTS_DIR}/" || true
  if [[ "${status}" -ne 0 || "${fom}" == "-" ]]; then
    echo "fsdp-llm ${model}: launcher exited ${status}, or no FOM line / implausible loss" >&2
    tail -n 60 "${logfile}" >&2 || true
    failed=1
    continue
  fi
  bk_emit_result \
    --fom "${fom}" \
    --fom-unit tokens/s \
    --fom-version llm-train-fsdp2-steady-v1 \
    --exp "llama-${model}-seq2048-tp${tp}-${dtype}" \
    --nodes "${nodes}" \
    --numproc-node "${numproc_node}" \
    --nthreads "${nthreads}" >> "${RESULTS_DIR}/result"
done
exit "${failed}"
