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
carries cuBLAS autotune), epoch 1 on CPUs. The experiment label carries the
local batch (`top-medium-pretrain-b128`): rows at different batches are
different workloads. Success marker: `Training Complete`.

| system | hardware | rows | local batch | events/s |
|---|---|---|---:|---:|
| RIKYU | B200 | 1 GPU | 128 | 739.2 |
| RC_GH200 | GH200 | 1 GPU | 128 | 593.5 |
| RC_DGXSP | GB10 (121 GB unified memory) | 1 GPU | 64 | 70.5 |
| RC_GENOA | EPYC 9684X (1 socket, 96 cores), 1 process x 64 threads | 1 node | 128 | 7.3 |
| Fugaku | A64FX, 4 ranks x 12 threads per node | 1 node | 8 | 14.4 |
| Fugaku | | 4 nodes | 8 | 51.3 |
| Fugaku | | 12 nodes | 8 | 132.8 |

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

**Fugaku.** Login nodes are x86 and compute nodes A64FX. The runtime is the
[pytorch-fugaku](https://github.com/william-dawson/pytorch-fugaku) image: the
official `torch==2.11.0` wheel plus torch_fugaku (a batch-parallel `bmm`, SVE
`gelu`/`gelu_backward`/`tanh`, oneDNN off, and DDP gradients summed over
Fujitsu MPI). `build.sh`, on the login node:

1. fetches OmniLearned and applies the timer patch, as on every system;
2. fetches pytorch-fugaku's launch scripts at a pinned commit;
3. installs OmniLearned's dependencies (`fugaku-requirements.txt`, exact
   versions) as aarch64 wheels into `artifacts/pydeps`, with a pinned static
   `uv` (the login node's Python is 3.6).

The build uses uv 0.13.4, which removes the compromised emSign CA trust
described in [GHSA-hq85-5cpj-mr62](https://github.com/astral-sh/uv/security/advisories/GHSA-hq85-5cpj-mr62).
Its x86_64 musl archive is downloaded to a unique temporary file and checked
against the SHA-256 pinned in `build.sh` before extraction or execution.
The pin comes from the [official 0.13.4 release asset metadata](https://github.com/astral-sh/uv/releases/tag/0.13.4);
review and update both version and digest together. Download, verification,
or extraction failure stops the build without running uv; a failed attempt
may retain the temporary archive for diagnosis. This does not verify the
SIF or lock the contents of dependency wheels. uv is a build-time tool,
not part of the training launcher.

Wheel installation requires an existing compatible Python interpreter on the
login node. If necessary, set `UV_PYTHON` to its executable before running the
build. Python downloads are disabled with `UV_PYTHON_DOWNLOADS=never` and
`--no-python-downloads`; if uv cannot find a suitable interpreter, the build
stops. The wheel target remains aarch64 / Python 3.10, independently of the
host interpreter (cross-installation was checked with Python 3.12).

`run.sh` launches as pytorch-fugaku describes: `pf-setup` once (it copies
the compute node's Tofu, PMIx and hwloc libraries for the containers and
writes the process-group settings), then `mpiexec -n <ranks> pf-run <sif>
python -m omnilearned.cli train ...`, one container per 12-core CMG with
Fujitsu MPI bound in from the host. Nothing from Fujitsu is in the image.

Each node's first rank reads the dataset into the page cache before
training. The config sets `num_workers: 0`: memory registered by Fujitsu MPI
is not fork-safe, so DataLoader workers crash. Batch 8 per rank fits the
8 GiB each rank gets of the node's 32 GiB HBM2.

**Note for maintainers: normal mode.** Fugaku jobs default to boost-eco
(`eco_state=2`), which caps the FP32 pipelines GEMMs use; normal mode
(`-L freq=2000,eco_state=0`) is ~1.1x faster here. The `FJ` queue template
has no per-app PJM options, so an app cannot request it; a site can, for
every app, with `BK_SCHEDULER_EXTRA_ARGS_Fugaku="-L freq=2000,eco_state=0"`.
The table gives the default-mode rows; normal mode is listed below.

| Fugaku, normal mode | 1 node | 4 nodes | 12 nodes |
|---|---:|---:|---:|
| events/s | 15.9 | 58.4 | 145.2 |

All six Fugaku rows were measured on 2026-10-28 through this `run.sh`; best
losses (9.40150, 9.56419, 9.37519 at 1, 4, 12 nodes) are identical across
modes. Repeated rows vary by up to ~5%.

## The Fugaku SIF

`build.sh` expects the image already staged (override with `BK_OMNILEARNED_SIF`):

| | |
|---|---|
| file | `/vol0200/share/ra000009/CX_input/omnilearned/pytorch-fugaku-ed93ef4.sif` |
| sha256 | `ba657626dafd515cbbd54c51e4962dcb8a21a242069c46553a122aa4a4d441b0` (2,983,251,968 bytes) |
| source | `docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:26d5947a434b241c9ed2a1ab2ae10219da9f756060bc05911e12c644f7d76498` (tag `sha-ed93ef4`, built by that repo's CI) |

To restage, on a Fugaku login node (keep Singularity's cache off `$HOME`):

```bash
export SINGULARITY_CACHEDIR=/vol0200/data/ra000009/.singularity
singularity pull --arch arm64 pytorch-fugaku-ed93ef4.sif \
  docker://ghcr.io/william-dawson/pytorch-fugaku@sha256:26d5947a434b241c9ed2a1ab2ae10219da9f756060bc05911e12c644f7d76498
```

## Dataset

### Runtime provenance

Before training, the launch-side process records the selected SIF's SHA-256
in the existing run environment snapshot, including `BK_OMNILEARNED_SIF`
overrides. Image observation and snapshot publication use the shared
`scripts/record_runtime_image.py IMAGE SNAPSHOT [UNAVAILABLE_REASON]` helper.
Other applications can call it with their selected image and run snapshot;
path selection, collection timing and time limits remain the caller's policy.
OmniLearned's dataset and DGX policies remain application-specific.
This identifies the observed file, not publisher verification or
the complete host environment. Missing, unreadable or changing images are
not reported as successfully observed. The build/source snapshot remains
separate; the SIF may differ between build and run. Replacement after the
observation is not prevented by this record.

The selected `BK_OMNILEARNED_DATA` root's `top/` tree is recorded once through
`bk_record_input`, before MPI launch and outside the training timer. This
describes staged inputs (including available index/manifest files), not a
claim that every split/file was consumed. Newly generated files and later
changes are not covered by that pre-launch observation. Hashing the staged
tree adds launch-side I/O; it is not repeated for every rank. Observation
is skipped on DGX Spark to preserve its deliberate no-warmup policy for
unified memory; the Result records unavailable content evidence and the
reason instead of reading the dataset. Each SIF/dataset collection is
limited to 30 seconds (optional `BK_OMNILEARNED_OBSERVATION_SECONDS`, integer
1--300), followed by up to two seconds of termination grace. Timed-out or
interrupted dataset captures are discarded rather than published partially.
Only complete staged records or explicit unavailable records are merged;
existing input entries are retained. Metadata publication is separately bounded.
Cleanup is also limited to two seconds plus two seconds of termination grace.
Cleanup failure or timeout warns and retains any remaining temporary files;
it does not turn observation housekeeping into a training failure.
Observation
failures do not change scientific acceptance or silently become verified
inputs. Dataset and host/MPI evidence are separate from the SIF hash.

SIFs are supported runtime artifacts. Recording their actual hashes is
distinct from checking downloaded artifacts against a trusted publisher
digest. The existing documented OCI digest and SIF hash are different
identifiers; this observation does not add acquisition verification.

The `top` dataset (Top Tagging Community benchmark; 1,211,000 train /
403,000 val / 403,000 test events, ~9.7 GB of HDF5), staged per site; paths
and checksums in `data/README.md`. Override with `BK_OMNILEARNED_DATA`.

## Known behaviors

- At 4+ GPU nodes a single rank can stall silently at an end-of-pass
  collective until the 600 s NCCL watchdog aborts the job (once in ~10
  runs, not reproducible). Rerun the row.
- The large (420M) model diverges at throughput-sized batches with the
  scratch configs' lr 5e-4; the pretrain lr (3e-5) is stable.
