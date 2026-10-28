# llm-pretrain

Training throughput of a large language model: a Llama-architecture decoder pretrained with
DeepSpeed ZeRO-3, the same script on every system. It measures how fast each machine trains
an LLM, so that machines of different generations (Fugaku, its GPU successors) compare on the
workload that drives AI-for-science procurement.

## What is measured

`llama_train.py`: a Llama 3.2-1B-shaped model (1,235,814,400 parameters: hidden 2048,
16 layers, 32 heads with 8 KV heads, FFN 8192, vocabulary 128,256, tied embeddings) from
`transformers`, randomly initialised from its config, trained on synthetic tokens at sequence
length 2048 with DeepSpeed ZeRO-3, AdamW (fused), gradient clipping 1.0. No dataset or
weights are downloaded. Ten steps; the first three are excluded.

**FOM: train tokens/s** = sequences per step x 2048 / steady step time, from the script's
`fom` line. The experiment label carries the precision
(`llama-3.2-1b-seq2048-bf16|fp32`). Success: the `fom` line and a final loss between 10 and 13
(random tokens give ln(128256) = 11.76).

Each machine trains at the precision it would use: **bf16 on GPUs, fp32 on CPUs**. A64FX has
no bf16 arithmetic, and the stock PyTorch wheel's fp16 matrix multiply runs at under
1 GFLOP/s on it.

| system | hardware | rows | sequences per rank | tokens/s | per node |
|---|---|---|---:|---:|---:|
| RIKYU | B200, bf16 | 1 node (4 GPUs) | 16 | 347,000 | 347,000 |
| RIKYU | | 2 nodes | 16 | 699,000 | 350,000 |
| RIKYU | | 4 nodes | 16 | 1,363,000 | 341,000 |
| RC_DGXSP | GB10 (121 GB unified), bf16 | 1 GPU | 8 | 4,552 | 4,552 |
| RC_GENOA | EPYC 9684X (96 cores), fp32, 4 ranks x 24 threads | 1 node | 1 | 292 | 292 |
| Fugaku | A64FX, fp32, 2 ranks x 24 threads | 4 nodes | 1 | 494 | 124 |
| Fugaku | | 32 nodes | 1 | 3,667 | 115 |
| Fugaku | A64FX, fp32, 4 ranks x 12 threads | 16 nodes | 1 | 2,218 | 139 |

RIKYU scales at 98% from 1 to 4 nodes. 16 sequences per GPU is the largest batch that fits a
B200 (32 does not); a GB10 holds 8. On Genoa 1 rank x 96 threads gives the same rate (289).
The Fugaku rows are untuned (below).

## How each system runs

**GPUs and Genoa.** `build.sh` makes a venv with torch 2.11.0, DeepSpeed 0.19.8 (no ops
prebuilt), transformers 4.57.6 and accelerate 1.15.0; Genoa takes the CPU wheel. `run.sh`
launches with `torchrun` (multi-node RIKYU: one agent per node through `srun`), NCCL on GPUs
and gloo on Genoa. DeepSpeed's CPU backend JIT-compiles a shared-memory op with the venv's
`ninja`, so the venv's `bin/` is on `PATH`.

**Fugaku.** Login nodes are x86 and compute nodes A64FX. The runtime is the
[pytorch-fugaku](https://github.com/william-dawson/pytorch-fugaku) image: the official torch
2.11.0 wheel plus torch_fugaku, whose `"fjmpi"` backend runs `torch.distributed`'s
collectives over Fujitsu MPI (gloo over Tofu TCP made a GPT-2-sized step 4-7x slower at 4 nodes). `build.sh`
fetches that repo's launch scripts at the image's commit and installs the Python stack as
aarch64 wheels into `artifacts/pydeps` with a pinned static `uv` (DeepSpeed's wheel is
built by uv; the login node's Python is 3.6). `run.sh` runs `pf-setup`, then one `pf-run`
container per rank under Fujitsu `mpiexec`.

Memory sets which layouts fit. Each A64FX rank has 8 GB (4 ranks per node) or 16 GB
(2 ranks per node), and the 128k vocabulary costs every rank about 5 GB however many nodes
share the model: the tied embedding gathered whole and its gradient, the fp32 logits, their
softmax and gradient. Activation checkpointing and smaller ZeRO-3 buffers (`--low-mem`:
1e8 live parameters, 2e7 prefetch, 5e7 reduce bucket) are on. With 2 ranks per node the
model trains from 4 nodes and scales flat to 32 (93% from 4). With 4 ranks per node it is
24% faster per node but fits only at 16 nodes: below that the model state does not fit, and
at 32 the node memory outside the processes (it grows with the rank count, likely MPI's
per-peer resources) leaves too little for the backward pass.

Not yet tuned: the step is 51-59% GEMM (about 37% of fp32 peak per CMG), 18% CPU attention
and 12-20% ZeRO-3 communication.

Normal mode (`-L freq=2000,eco_state=0`) was used for the Fugaku rows. The `FJ` queue
template has no per-app PJM options, so a site sets it for every app with
`BK_SCHEDULER_EXTRA_ARGS_Fugaku="-L freq=2000,eco_state=0"`.

### The Fugaku SIF

| | |
|---|---|
| file | `/vol0200/share/ra000009/CX_input/llm-pretrain/pytorch-fugaku-86dda25.sif` (override with `BK_LLM_PRETRAIN_SIF`) |
| sha256 | `68f2039fc56f5b6f5ef03aeb2f515f2f27138ee2f0fcefae7260af32d9120b80` (2,983,428,096 bytes) |
| source | `docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:41ea3d8fff24514432b5717e7df1782865ce1fb26cb11b531b6e684b6adfd330` (commit `86dda25`, built by that repo's CI) |

To restage on a Fugaku login node (keep Singularity's cache off `$HOME`):

```bash
export SINGULARITY_CACHEDIR=/vol0200/data/ra000009/.singularity
singularity pull --arch arm64 pytorch-fugaku-86dda25.sif \
  docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:41ea3d8fff24514432b5717e7df1782865ce1fb26cb11b531b6e684b6adfd330
```

## Reference

Fugaku-LLM (2024) trained a 13B model on 380B tokens on 13,824 Fugaku nodes with a Fugaku
port of Megatron-DeepSpeed
([Fugaku-LLM/DeepSpeedFugaku](https://github.com/Fugaku-LLM/DeepSpeedFugaku)). Its throughput
is not published in a form this FOM can be compared with.
