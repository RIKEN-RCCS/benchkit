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
logfile="${PWD}/train.log"
export OMP_NUM_THREADS="${nthreads}" NNODES="${nodes}" TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
# DeepSpeed's CPU backend JIT-compiles its shared-memory op with the venv's ninja.
export PATH="${ARTIFACT_DIR}/venv/bin:${PATH}"

# Each machine trains at the precision it would use: bf16 on GPUs, fp32 on CPUs (A64FX has no
# bf16, and the stock wheel's fp16 GEMM runs at <1 GFLOP/s). The micro-batch per rank is the
# largest that fits; see README.md.
COMMON=(--model 1b --seq 2048 --zero 3 --steps 10 --warmup 3)

case "${system}" in
  RIKYU)
    module load cuda/13.2.2
    ARGS=("${COMMON[@]}" --dtype bf16 --micro-batch 16 --backend nccl)
    if [[ "${nodes}" -eq 1 ]]; then
      "${ARTIFACT_DIR}/venv/bin/torchrun" --standalone --nproc_per_node="${numproc_node}" \
        "${ARTIFACT_DIR}/llama_train.py" "${ARGS[@]}" > "${logfile}" 2>&1 || true
    else
      # One torchrun agent per node; --ntasks pins one task per node in a 4-tasks-per-node allocation.
      MASTER_ADDR=$(scontrol show hostnames "${SLURM_JOB_NODELIST}" | head -n 1)
      srun --ntasks="${nodes}" --ntasks-per-node=1 "${ARTIFACT_DIR}/venv/bin/torchrun" --nnodes="${nodes}" \
        --nproc_per_node="${numproc_node}" --rdzv_backend=c10d --rdzv_endpoint="${MASTER_ADDR}:29500" \
        "${ARTIFACT_DIR}/llama_train.py" "${ARGS[@]}" > "${logfile}" 2>&1 || true
    fi
    ;;
  RC_DGXSP)
    # Unified memory: expandable segments keep the allocator from fragmenting it.
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    "${ARTIFACT_DIR}/venv/bin/torchrun" --standalone --nproc_per_node="${numproc_node}" \
      "${ARTIFACT_DIR}/llama_train.py" "${COMMON[@]}" --dtype bf16 --micro-batch 8 --backend nccl \
      > "${logfile}" 2>&1 || true
    ;;
  RC_GENOA)
    export DS_ACCELERATOR=cpu
    mb=$(( numproc_node >= 4 ? 1 : 4 / numproc_node ))
    "${ARTIFACT_DIR}/venv/bin/torchrun" --standalone --nproc_per_node="${numproc_node}" \
      "${ARTIFACT_DIR}/llama_train.py" "${COMMON[@]}" --dtype fp32 --micro-batch "${mb}" --backend gloo \
      > "${logfile}" 2>&1 || true
    ;;
  Fugaku)
    # pytorch-fugaku's launch: pf-setup collects the compute node's Tofu libraries and the
    # process-group settings; one pf-run container per rank under Fujitsu mpiexec, collectives
    # over Fujitsu MPI (torch_fugaku's "fjmpi" backend). Rank 0 logs to train.log.
    SIF="${BK_DEEPSPEED_LLM_SIF:-/vol0200/share/ra000009/CX_input/deepspeed-llm/pytorch-fugaku-08033f4.sif}"
    export PF_DIR="${ARTIFACT_DIR}/pytorch-fugaku/fugaku" SIF logfile DS_ACCELERATOR=cpu
    export PF_HOSTLIB="${PWD}/.pf-hostlib" PF_BIND="${PWD}:/work:rw"
    export PYTHONPATH=/work/artifacts/pydeps SINGULARITYENV_PREPEND_PATH=/work/artifacts/pydeps/bin
    export TORCH_EXTENSIONS_DIR=/work/artifacts/torch-ext
    # 8 GB per rank: activation checkpointing and smaller ZeRO-3 buffers (README: "Fugaku").
    export LLM_ARGS="${COMMON[*]} --dtype fp32 --micro-batch 1 --backend fjmpi --checkpointing --low-mem"
    "${PF_DIR}/pf-setup" "${numproc_node}"
    mpiexec -n "${n_ranks}" bash -c '
      log=/dev/null; [[ ${PMIX_RANK} -eq 0 ]] && log="${logfile}"
      exec "${PF_DIR}/pf-run" "${SIF}" python /work/artifacts/llama_train.py ${LLM_ARGS} > "${log}" 2>&1' || true
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

# Success: the script's own FOM line, and a final loss that is finite and near ln(vocab) = 11.76
# (random tokens, random init) -- not the launcher's exit code.
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
ok = fom is not None and last is not None and math.isfinite(last) and 10.0 < last < 13.0
print(fom["tokens_per_s"] if ok else "-")
PY
)"
if [[ "${fom}" == "-" ]]; then
  echo "deepspeed-llm: no FOM line or implausible loss" >&2
  tail -n 60 "${logfile}" >&2 || true
  exit 1
fi

dtype=fp32; [[ "${system}" == RIKYU || "${system}" == RC_DGXSP ]] && dtype=bf16
bk_emit_result \
  --fom "${fom}" \
  --fom-unit tokens/s \
  --fom-version llama-train-steady-v1 \
  --exp "llama-3.2-1b-seq2048-${dtype}" \
  --nodes "${nodes}" \
  --numproc-node "${numproc_node}" \
  --nthreads "${nthreads}" >> "${RESULTS_DIR}/result"

cp "${logfile}" "${RESULTS_DIR}/train.log"
