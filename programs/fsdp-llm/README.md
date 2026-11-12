# fsdp-llm

LLM pretraining throughput with PyTorch FSDP2 (`fully_shard`), the same script on every
system. Two models: a 30B, the configuration in Fugaku-LLM's DeepSpeedFugaku, trained with
tensor parallel inside each node and FSDP2 across nodes; and a 1B that every system can train,
including a single DGX Spark. It tests compute, the collectives, and whether a model's state
fits.

## What is measured

`llm_train.py` builds a Llama-architecture decoder from `transformers` on the meta device,
shards it, initializes each shard randomly (N(0, 0.02), norms 1) and trains it on synthetic
tokens at sequence length 2048 with AdamW. No dataset or weights are downloaded. Five steps;
the first two are excluded.

| model | shape | parameters |
|---|---|---:|
| `30b` | DeepSpeedFugaku's GPT-30B as a Llama: 48 layers, hidden 6912, 72 heads (full multi-head attention), SwiGLU MLP 18432 (GPT's 12 h² weights per layer), vocabulary 50,304 | 28,214,901,504 |
| `1b` | Llama 3.2-1B: 16 layers, hidden 2048, 32 heads with 8 KV heads, MLP 8192, vocabulary 128,256 | 1,498,482,688 |

Embeddings are untied in both, so tensor parallel can shard them separately.

**FOM: train tokens/s** = tensor-parallel groups x sequences per group x 2048 / steady step
time, from the script's `fom` line. Each row reports one Result per model it runs; the
experiment label carries the model, the tensor-parallel size and the precision
(`llama-{1b,30b}-seq2048-tp{1,4}-{bf16,fp32}`). Success: a clean launcher exit, the `fom` line,
and a final loss between 9 and 14 (random tokens give ln(vocab) plus about half the logit
variance at initialization: 12.2 for both models).

## Parameter choices

- **Which model.** RIKYU rows run both models, the Spark and Genoa the 1B, Fugaku the 1B below
  64 nodes and the 30B from 64.
- **Parallelism.** The 30B uses tensor parallel within a node (`--tp` = ranks per node) and
  FSDP2 across nodes: q/k/v and gate/up column-parallel, o and down row-parallel, the
  embedding, `lm_head` and the loss vocab-parallel, sequence parallel for the norms and the
  residual stream. The 1B uses FSDP2 alone (`--tp 1`), where tensor parallel only adds
  communication: 242k against 71-83k tokens/s per node on RIKYU, 386 against 263 on Genoa.
  Fugaku keeps tensor parallel 4 for the 1B, since a rank's ~7 GB cannot hold the
  128k-vocabulary loss beyond one sequence.
- **Precision.** What each machine would train with: bf16 compute on GPUs (FSDP2 mixed
  precision: fp32 parameters, gradient reduction and AdamW), fp32 on CPUs (A64FX has no bf16).
- **Batch.** Sequences per tensor-parallel group, the largest that fits or where throughput
  stops improving (sweeps below).
- **Memory.** Activation checkpointing per layer everywhere.
- **Layout.** Fugaku 4 ranks x 12 threads, one rank per CMG; Genoa 16 x 6; one rank per GPU,
  with 16 cores per rank on RIKYU (5% over one).

## Results

Every row is this `run.sh`, submitted with `scripts/test_submit.sh` (R-CCS Cloud after
`scripts/test_submit_build.sh`), on 2026-11-05. Tokens/s per node:

| system | hardware | rows | 1B | 30B |
|---|---|---|---:|---:|
| RIKYU | 4 x B200, bf16 | 1 / 2 / 4 nodes | 243,083 / 243,081 / 240,640 | 12,586 / 12,554 / 12,368 |
| RC_DGXSP | GB10 (128 GB unified), bf16 | 1 | 3,537 | - |
| RC_GENOA | 2 x EPYC 9684X (768 GB), fp32 | 1 | 384 | - |
| Fugaku | A64FX, fp32 | 4 / 16 nodes | 177.7 / 176.0 | - |
| Fugaku | | 64 / 128 / 256 nodes | - | 7.6-9.0 / 7.5 / 7.5 |

- **RIKYU.** 1B: 16 sequences per GPU, 0.54 s steps, 54 GB per GPU (32 ran 3% faster at
  104 GB). 30B: 64 per group, about 11 s steps, 128 / 89 / 69 GB per GPU at 1 / 2 / 4 nodes;
  per node, 1 sequence ran 373 tokens/s, 8 ran 2,992, 32 ran 11,427, 64 ran 12,020 and 128
  ran 11,613-11,886 at nearly twice the memory.
- **DGX Spark.** 16 sequences, 82 GB of the 128 GB; 4 and 8 ran 2,738 and 3,131 tokens/s, and
  32 was killed for memory. The 30B (about 450 GB of state with AdamW) does not fit.
- **Genoa.** 1B: 4 sequences per rank, 342 s steps (1 and 2 ran 274 and 331 tokens/s). The 30B
  fits (tensor parallel 4 x 4 data-parallel groups, 1 sequence each, 33 GB per rank) and ran
  13.1 tokens/s per node on 2026-11-05, but at 624 s steps a row takes an hour, so Genoa runs
  the 1B only.
- **Fugaku.** Normal mode. 1B: 4 sequences per group, 47 s steps, 6.4 GB per rank. 30B:
  1 sequence per group, 4.2-5.2 GB per rank; three 64-node allocations ran 227, 238 and 271 s
  steps with identical losses, and 128 / 256 nodes 272 / 274 s (those two on the previous revision of `run.sh`, with the
  same 30B arguments). Step time varies by up to ~25%
  between allocations of the same size (the communication share, not compute).

For scale: DeepSpeedFugaku's Megatron-DeepSpeed ran the 30B configuration (as GPT,
`30b_pp8_tp6_dp12`) on 576 nodes at about 6 tokens/s per node: 909-946 s per iteration of
1536 x 2048 tokens in two 5-iteration runs from December 2023 (1 rank x 48 threads per node,
TP 6 x PP 8 x DP 12).

## How each system runs

**GPUs and Genoa.** `build.sh` makes a venv with torch 2.11.0 and transformers 4.57.6 (Genoa
the CPU wheel). `run.sh` launches with `torchrun`: NCCL on GPUs (multi-node RIKYU through
`srun`, one agent per node), gloo on Genoa.

**Fugaku.** Login nodes are x86 and compute nodes A64FX. The runtime is the
[pytorch-fugaku](https://github.com/william-dawson/pytorch-fugaku) image: the official torch
2.11.0 wheel, transformers, and torch_fugaku, whose `"fjmpi"` backend runs `torch.distributed`'s
collectives over Fujitsu MPI. Nothing from Fujitsu is in the image; its MPI is bound in from
the host. `build.sh` fetches that repo's launch scripts at the image's commit. `run.sh` runs
`pf-setup`, then one `pf-run` container per rank under Fujitsu `mpiexec`. The process group
is created with `init_method="fjmpi://"`: rank and size from the launcher, no TCP
rendezvous, which failed from about 1000 ranks. `MIMALLOC_PURGE_DELAY=0` makes torch's bundled
allocator return freed memory (peak 5.8 → 3.8 GB per rank in a 30B probe).

The first step takes several times a steady step, and how much depends on the allocation
(70 s and 1195 s in two simultaneous 256-node jobs on the same image), so it is excluded with
the second.

Normal mode (`-L freq=2000,eco_state=0`) is assumed. The `FJ` queue template has no per-app
PJM options, so a site sets it for every app with
`BK_SCHEDULER_EXTRA_ARGS_Fugaku="-L freq=2000,eco_state=0"`.

## The Fugaku SIF

`build.sh` downloads the pytorch-fugaku image (commit `d7fb755`, built by that repo's CI) into
`artifacts/` and checks its SHA-256. The download is HTTPS from a public registry, needs no
credentials, and is pinned by digest. `BK_FSDP_LLM_SIF` selects a pre-staged file instead (not
checked); `run.sh` records the SHA-256 of the SIF it ran in the run's environment snapshot.

| | |
|---|---|
| file | `pytorch-fugaku-d7fb755.sif`, 3,044,311,040 bytes |
| sha256 | `267d5a25ca5bbbfe10860c09529697e54af57c6012b53c2c7701fdfb1f96fd08` |
| also | `singularity pull oras://ghcr.io/william-dawson/pytorch-fugaku@sha256:ae940a522a26945571de0eea9c8b6962392102cddca69d9ca75c3eb6f0f9f245` (tag `sif-d7fb755`), on an arm64 host: Singularity rejects the file on the x86 login node |
| image | `docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:ac92e7ace93cfea2ccd5f4f92e14f2d19aa0c65fe3ea83bf57f2ddf35d8c218e` |

The SIF is published as a file by that repo's CI, not converted at each site, because converting
the same image twice gives files with different SHA-256s. `build.sh` fetches it as a registry blob
addressed by its SHA-256, the same as:

```bash
T=$(curl -s "https://ghcr.io/token?scope=repository:william-dawson/pytorch-fugaku:pull" | sed 's/.*"token":"\([^"]*\)".*/\1/')
curl -L -H "Authorization: Bearer $T" -o pytorch-fugaku-d7fb755.sif \
  https://ghcr.io/v2/william-dawson/pytorch-fugaku/blobs/sha256:267d5a25ca5bbbfe10860c09529697e54af57c6012b53c2c7701fdfb1f96fd08
sha256sum pytorch-fugaku-d7fb755.sif
```

## Reference

Fugaku-LLM (2024) trained a 13B model on 380B tokens on 13,824 Fugaku nodes with a Fugaku
port of Megatron-DeepSpeed
([Fugaku-LLM/DeepSpeedFugaku](https://github.com/Fugaku-LLM/DeepSpeedFugaku)).
