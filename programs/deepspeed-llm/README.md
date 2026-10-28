# deepspeed-llm

DeepSpeed training throughput: a Llama-architecture LLM trained with DeepSpeed ZeRO-3, the
same script on every system. It tests how well a machine runs DeepSpeed's sharded data
parallelism at LLM scale (its compute, its collectives and the memory per rank ZeRO-3 needs),
so that machines of different generations (Fugaku, its GPU successors) compare on the
software stack LLM training actually uses.

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
| RIKYU | B200, bf16 | 1 node (4 GPUs) | 16 | 351,900 | 351,900 |
| RIKYU | | 2 nodes | 16 | 699,500 | 349,700 |
| RIKYU | | 4 nodes | 16 | 1,370,800 | 342,700 |
| RC_DGXSP | GB10 (121 GB unified), bf16 | 1 GPU | 8 | 4,563 | 4,563 |
| RC_GENOA | EPYC 9684X (96 cores), fp32, 16 ranks x 6 threads | 1 node | 1 | 455 | 455 |
| Fugaku | A64FX, fp32, 2 ranks x 24 threads | 4 nodes | 1 | 609 | 152 |
| Fugaku | | 32 nodes | 1 | 4,474 | 140 |
| Fugaku | A64FX, fp32, 4 ranks x 12 threads, Fujitsu BLAS | 16 nodes | 1 | 3,112 | 195 |

Every row is this `run.sh` on 2026-10-28; RIKYU scales at 97% from 1 to 4 nodes. Genoa runs best with many small
ranks: 290 tokens/s at 4 x 24, 376 at 8 x 12, 438 at 12 x 8, 458 at 16 x 6, 453 at 24 x 4; SMT
adds nothing. 16 sequences per GPU is the largest batch that fits
a B200 (32 does not); a GB10 holds 8. The
Fugaku rows are partly tuned (below).

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
28-39% faster per node (195 tokens/s against 152 at 4 nodes and 140 at 32; Fujitsu BLAS,
below, is part of that) but fits only at 16 nodes: below that the model state does not fit, and
at 32 the node memory outside the processes (it grows with the rank count, likely MPI's
per-peer resources) leaves too little for the backward pass.

Tuning so far, all in torch_fugaku: a threaded 2-norm for gradient clipping; reduce-scatter
as an all-to-all and a local sum (Fujitsu MPI's own ran ~10x below its all-gather); and
`X . W^T` (`nn.Linear`'s forward, slow through NVPL's transposed-B GEMM on A64FX) through a
NEON transpose and the plain GEMM, 4x on Llama's `down_proj`. On the 4-ranks-per-node row
`run.sh` also sets `PF_FJBLAS=1`, which sends `mm`/`addmm` to Fujitsu's threaded BLAS
(`libfjlapackexsve`, from the host's compiler mount, never baked into the image) with
`OMP_PROC_BIND=false`, since any binding pins Fujitsu's OpenMP to one core: 17% on that row.
The 2-ranks rows stay on NVPL until the same route is checked at 24 threads per rank. At 16
nodes x 4 ranks the step is now 43% GEMM (73% of fp32 peak), 26% CPU attention and 15%
ZeRO-3 communication; the whole step runs at about 35% of peak, recompute included.

Normal mode (`-L freq=2000,eco_state=0`) was used for the Fugaku rows. The `FJ` queue
template has no per-app PJM options, so a site sets it for every app with
`BK_SCHEDULER_EXTRA_ARGS_Fugaku="-L freq=2000,eco_state=0"`.

### The Fugaku SIF

| | |
|---|---|
| file | `/vol0200/share/ra000009/CX_input/deepspeed-llm/pytorch-fugaku-b5879f2.sif` (override with `BK_DEEPSPEED_LLM_SIF`) |
| sha256 | `2bc3dd0549f96a3ee8a61d975a8a4a979cd47ddb0d0548dc57811b86a73e5003` (2,983,469,056 bytes) |
| source | `docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:95bc28f987d963653c8e46e2b5a00d7e4857559292c611d079723ce0de3896db` (commit `b5879f2`, built by that repo's CI) |

To restage on a Fugaku login node (keep Singularity's cache off `$HOME`):

```bash
export SINGULARITY_CACHEDIR=/vol0200/data/ra000009/.singularity
singularity pull --arch arm64 pytorch-fugaku-b5879f2.sif \
  docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:95bc28f987d963653c8e46e2b5a00d7e4857559292c611d079723ce0de3896db
```

## Reference

Fugaku-LLM (2024) trained a 13B model on 380B tokens on 13,824 Fugaku nodes with a Fugaku
port of Megatron-DeepSpeed
([Fugaku-LLM/DeepSpeedFugaku](https://github.com/Fugaku-LLM/DeepSpeedFugaku)). Its throughput
is not published in a form this FOM can be compared with.
