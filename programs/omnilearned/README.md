# omnilearned

Training throughput of [OmniLearned](https://github.com/ViniciusMikuni/OmniLearned),
the foundation-model framework for jet physics of Bhimji, Harris, Mikuni and
Nachman (PRD **113**, 032020; arXiv:2510.24066): PET v2 point-cloud
transformers trained jointly on classification and flow-matching generation.

## What is measured

The paper's **pretraining** step on the portable `top` dataset
(`top_medium_pretrain.yaml`): `mode: pretrain`, the medium model
(58,844,756 parameters, the paper's "58M"), FP32, lr 3e-5, local batch 128
(global 4096 at 32 GPUs, the paper's operating point).

**FOM: train events/s** = iterations x local batch x ranks / train-pass wall
time. The wall time comes from a 6-line patch (`patches/train_pass_timer.patch`)
because the stock epoch timer also covers validation and the checkpoint
save. The last `Train pass wall` line is used: epoch 2 on GPUs (epoch 1
carries cuBLAS autotune), the only epoch on Genoa. The experiment label carries the
local batch (`top-medium-pretrain-b128`): rows at different batches are
different workloads. Success marker: `Training Complete`.

| system | hardware | rows | local batch | events/s |
|---|---|---|---:|---:|
| RIKYU | B200 | 1 GPU | 128 | 739.2 |
| RC_GH200 | GH200 | 1 GPU | 128 | 593.5 |
| RC_DGXSP | GB10 (121 GB unified memory) | 1 GPU | 64 | 70.5 |
| RC_GENOA | EPYC 9684X (1 socket, 96 cores), 1 process x 64 threads | 1 node | 128 | 7.3 |

On RIKYU the same config scales 3.65x at 4 GPUs, 7.17x at 8 (2 nodes) and
25.70x at 32 (8 nodes, global batch 4096; launched by direct `sbatch`, since
the agent tooling caps requests at 16 GPUs). The RC_GENOA row runs the stock
settings and has not been tuned.

## How each system runs

**GPUs and Genoa.** `build.sh` makes a venv with `torch==2.11.0` (on
aarch64 PyPI ships the CUDA wheel) and installs OmniLearned. `run.sh` uses
`torchrun`, not the repo's `srun`-based `shell/run.sh`:
`omnilearned.utils.ddp_setup()` reads only `RANK`/`LOCAL_RANK`/`WORLD_SIZE`.
Multi-node runs one agent per node; the inner `srun` must pin `--ntasks` to
the node count, or a 4-tasks-per-node allocation launches an agent per task
and the rendezvous collapses. The dataset is read into the page cache
before training: cold random HDF5 reads from group storage run to ~8 s per
batch. Not on RC_DGXSP, where the cache competes with the GPU for unified
memory (that row runs b64 for the same reason).

## Dataset

The `top` dataset (Top Tagging Community benchmark; 1,211,000 train /
403,000 val / 403,000 test events, ~9.7 GB of HDF5), staged per site; paths
and checksums in `data/README.md`. Override with `BK_OMNILEARNED_DATA`.

## Known behaviors

- At 4+ GPU nodes a single rank can stall silently at an end-of-pass
  collective until the 600 s NCCL watchdog aborts the job (once in ~10
  runs, not reproducible). Rerun the row.
- The large (420M) model diverges at throughput-sized batches with the
  scratch configs' lr 5e-4; the pretrain lr (3e-5) is stable.
