#!/bin/bash
set -euo pipefail

system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
n_ranks=$((nodes * numproc_node))

source scripts/bk_functions.sh

ARTIFACT_DIR="${PWD}/artifacts"
VENV="${ARTIFACT_DIR}/venv"
RESULTS_DIR="${PWD}/results"
mkdir -p "${RESULTS_DIR}"
: > "${RESULTS_DIR}/result"

# The `top` dataset is pre-staged per system (data/README.md); nothing is
# downloaded at benchmark time. The dataloader appends <dataset>/<split> to
# the configured path.
case "${system}" in
  RIKYU) DATA="${BK_OMNILEARNED_DATA:-/data1/rkp00015/CX_input/omnilearned/top}" ;;
  RC_GH200|RC_DGXSP|RC_GENOA) DATA="${BK_OMNILEARNED_DATA:-/lvs0/dne1/rccs-nghpcadu/CX_input/omnilearned/top}" ;;
  Fugaku) DATA="${BK_OMNILEARNED_DATA:-/vol0200/share/ra000009/CX_input/omnilearned}" ;;
  *) echo "Unknown system: ${system}" >&2; exit 1 ;;
esac

# Per-system config: DGX Spark's unified memory holds only b64; Genoa runs
# 25 iterations (18 s/step); Fugaku runs b8 per rank, one rank per CMG.
CONFIG_TEMPLATE="${ARTIFACT_DIR}/top_medium_pretrain.yaml"
case "${system}" in
  RC_DGXSP) CONFIG_TEMPLATE="${ARTIFACT_DIR}/top_medium_pretrain_b64.yaml"
            export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True ;;
  RC_GENOA) CONFIG_TEMPLATE="${ARTIFACT_DIR}/top_medium_pretrain_cpu.yaml" ;;
  Fugaku) CONFIG_TEMPLATE="${ARTIFACT_DIR}/top_medium_pretrain_fugaku.yaml" ;;
esac
CONFIG="${PWD}/omnilearned_bench.yaml"
# Fugaku runs in a container where the dataset is bind-mounted at /cx_input.
datapath="${DATA}"; [[ "${system}" == "Fugaku" ]] && datapath=/cx_input
sed "s|__OMNILEARNED_DATA__|${datapath}|" "${CONFIG_TEMPLATE}" > "${CONFIG}"

export OMP_NUM_THREADS="${nthreads}" HDF5_USE_FILE_LOCKING=FALSE TOKENIZERS_PARALLELISM=false

# Cold random HDF5 reads from group storage run to ~8 s/batch; the dataset
# fits in RAM, so read it once before training. Not on DGX Spark (the cache
# competes with the GPU for unified memory); on Fugaku each node's first
# rank does it (below).
if [[ "${system}" != "RC_DGXSP" && "${system}" != "Fugaku" ]]; then
  for f in "${DATA}"/*/*.h5; do cat "$f" > /dev/null; done
fi

logfile="train.log"
touch .run_marker

case "${system}" in
  RIKYU|RC_GH200|RC_DGXSP|RC_GENOA)
    # torchrun replaces the repo's srun-based shell/run.sh: ddp_setup() reads
    # only RANK/LOCAL_RANK/WORLD_SIZE. Multi-node is one agent per node; the
    # inner srun pins --ntasks to the node count, or a 4-tasks-per-node
    # allocation launches an agent per task and the rendezvous collapses.
    if [[ "${nodes}" -eq 1 ]]; then
      "${VENV}/bin/torchrun" --standalone --nproc_per_node="${n_ranks}" \
        -m omnilearned.cli train --config "${CONFIG}" > "${logfile}" 2>&1 || true
    else
      MASTER_ADDR=$(scontrol show hostnames "${SLURM_JOB_NODELIST}" | head -n 1)
      srun --ntasks="${nodes}" --ntasks-per-node=1 \
        "${VENV}/bin/torchrun" --nnodes="${nodes}" --nproc_per_node="${numproc_node}" \
        --node_rank="${SLURM_NODEID}" --rdzv_backend=c10d --rdzv_endpoint="${MASTER_ADDR}:29500" \
        -m omnilearned.cli train --config "${CONFIG}" > "${logfile}" 2>&1 || true
    fi
    ;;
  Fugaku)
    # pytorch-fugaku's launch: pf-setup collects the compute node's Tofu
    # libraries and the process-group settings, then one pf-run container per
    # rank under Fujitsu mpiexec. Rank 0 logs to train.log; each node's first
    # rank reads the dataset into that node's page cache.
    SIF="${BK_OMNILEARNED_SIF:-/vol0200/share/ra000009/CX_input/omnilearned/pytorch-fugaku-ed93ef4.sif}"
    export PF_DIR="${ARTIFACT_DIR}/pytorch-fugaku/fugaku" SIF DATA numproc_node
    export PF_HOSTLIB="${PWD}/.pf-hostlib"
    export PF_BIND="${PWD}:/work:rw,${DATA}:/cx_input:rw"
    export PYTHONPATH=/work/artifacts/pydeps:/work/OmniLearned/src PYTHONUNBUFFERED=1
    "${PF_DIR}/pf-setup" "${numproc_node}"
    mpiexec -n "${n_ranks}" bash -c '
      R=${PMIX_RANK}; log=train.rank${R}.log; [[ ${R} -eq 0 ]] && log=train.log
      if (( R % numproc_node == 0 )); then
        for f in "${DATA}"/top/*/*.h5; do cat "$f" > /dev/null; done
      fi
      exec "${PF_DIR}/pf-run" "${SIF}" \
        python -m omnilearned.cli train --config /work/omnilearned_bench.yaml > "${log}" 2>&1' || true
    ;;
esac

# Success marker is the app's own completion line, not the launcher's exit
# code: a crashed rank can still exit cleanly through the launcher.
if ! grep -q "Training Complete" "${logfile}"; then
  echo "omnilearned success marker not found" >&2
  tail -n 80 "${logfile}" >&2 || true
  exit 1
fi

# FOM = iterations x batch x ranks / train-pass wall, from the LAST
# "Train pass wall" line (epoch 2 where there are two: epoch 1 carries cuBLAS
# autotune and first-touch costs).
train_pass=$(grep "Train pass wall" "${logfile}" | tail -n 1 | sed -E 's/.*: ([0-9.]+) sec/\1/')
iterations=$(grep -E "^iterations:" "${CONFIG}" | awk '{print $2}')
batch=$(grep -E "^batch:" "${CONFIG}" | awk '{print $2}')
fom=$(python3 -c "print(f'{${iterations} * ${batch} * ${n_ranks} / ${train_pass}:.1f}')")

# Rows at different local batch are different workloads; the label says which.
bk_emit_result \
  --fom "${fom}" \
  --fom-unit events/s \
  --fom-version pretrain-ep2-trainpass \
  --exp "top-medium-pretrain-b${batch}" \
  --nodes "${nodes}" \
  --numproc-node "${numproc_node}" \
  --nthreads "${nthreads}" >> "${RESULTS_DIR}/result"

cp "${logfile}" "${RESULTS_DIR}/train.log"
