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
| Fugaku | A64FX, fp32, 2 ranks x 24 threads | 4 nodes | 1 | 441 | 110 |
| Fugaku | A64FX, fp32, 4 ranks x 12 threads | 16 nodes | 1 | 1,939 | 121 |

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

Memory sets the minimum node count. Each A64FX rank has 8 GB (4 ranks per node) or 16 GB
(2 ranks per node), and the 128k vocabulary costs every rank about 5 GB however many nodes
share the model: the tied embedding gathered whole and its gradient, the fp32 logits, their
softmax and gradient. Activation checkpointing and smaller ZeRO-3 buffers (`--low-mem`:
1e8 live parameters, 2e7 prefetch, 5e7 reduce bucket) are on. With 4 ranks per node the
model trains from 16 nodes; with 2 ranks per node, from 4.

Not yet tuned: at 16 nodes the step is 55% GEMM (about 38% of fp32 peak), 17% CPU attention
and 20% ZeRO-3 communication, most of it reduce-scatter through fjmpi's 8 MB staging buffer.

Normal mode (`-L freq=2000,eco_state=0`) was used for the Fugaku rows. The `FJ` queue
template has no per-app PJM options, so a site sets it for every app with
`BK_SCHEDULER_EXTRA_ARGS_Fugaku="-L freq=2000,eco_state=0"`.

### The Fugaku SIF

| | |
|---|---|
| file | `/vol0200/share/ra000009/CX_input/llm-pretrain/pytorch-fugaku-4bd4b96.sif` (override with `BK_LLM_PRETRAIN_SIF`) |
| sha256 | `91dc41aec2d949d7aa251d449a46de0877b2f6752f9a334406fcdba8acdf63be` (2,983,411,712 bytes) |
| source | `docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:783949c36b1796181be2c16c973bf046947c7d73e62e80887c5ee0a2b3e10e0c` (commit `4bd4b96`, built by that repo's CI) |

To restage on a Fugaku login node (keep Singularity's cache off `$HOME`):

```bash
export SINGULARITY_CACHEDIR=/vol0200/data/ra000009/.singularity
singularity pull --arch arm64 pytorch-fugaku-4bd4b96.sif \
  docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:783949c36b1796181be2c16c973bf046947c7d73e62e80887c5ee0a2b3e10e0c
```

## Reference

Fugaku-LLM (2024) trained a 13B model on 380B tokens on 13,824 Fugaku nodes with a Fugaku
port of Megatron-DeepSpeed
([Fugaku-LLM/DeepSpeedFugaku](https://github.com/Fugaku-LLM/DeepSpeedFugaku)). Its throughput
is not published in a form this FOM can be compared with.
