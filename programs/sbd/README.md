# SBD benchmark

This BenchKit application runs the NVIDIA Thrust TPB selected-basis
diagonalization benchmark from `github.com/r-ccs-cms/sbd`.

## Optional NSYS / NCU profiling

SBD keeps ordinary benchmark timing unprofiled, then collects a separate
profiling run on supported NVIDIA GPU systems. Set `BK_SBD_NCU_PROFILE=false`
or `SBD_PROFILER_TOOL=none` to skip the additional profile flow. The profile
flow runs rank-0 host
`nsys profile --trace=cuda --sample=none`, exports the CUDA kernel summary,
generates discovery and plan JSON in a common-owned `results/profile_<id>/` directory,
and then uses that plan for rank-0 Nsight Compute acquisition when
`BK_SBD_NCU_PROFILE_MODE=discovery`.

Use `BK_SBD_NCU_PROFILE_MODE=discovery-only` to stop after the NSYS discovery
and plan generation step. `BK_SBD_NCU_PLAN_TOP_K` controls how many kernels are
selected; discovery-only defaults to all kernels, while discovery defaults to
the top three. The RIKYU system default overrides this selection to the top one.
Generated NCU archives are attached to the `mult` section as
measurement artifacts.

## Workflow stage timing

SBD uses the common execution helpers for its ordinary benchmark, NSYS
collection/export, NCU plan generation and NCU collection/export. Benchkit
automatically logs and stores their stage timings as Measurement Artifacts;
the application does not manage timing records. See the
[shared profiler guide](../../docs/guides/profiler-support.md#workflow-stage-timing)
for scope, failure handling and interpretation. The internal Davidson FOM
remains independent of workflow wall time.

## Benchmark recipes

The RIKYU recipe uses the H2O cc-pVDZ FCIDUMP with the `1em7` selected alpha
determinant file (about 628 million product determinants), one MPI rank per
B200 GPU, 32 OpenMP threads per rank, and the rank-distributed/index-reordered/NCCL
build configuration validated in the SubWG2 benchmark study. 32 threads is
Rikyu's site-enforced CPU cap per requested GPU on shared nodes; it also
covers the pre-Davidson setup pass (`RemakeHelpers`/`TaskCostSize`), which
runs on the host rather than the GPU and is slow to the point of resembling
a hang on large inputs if starved of threads. The inputs are staged from the
SBD source clone into `artifacts/` by `build.sh` (see
`data/h2o/README.md` for provenance) and can be overridden with
`BK_SBD_INPUT_DIR` when a project-storage copy is preferred.

The DGX Spark route uses the H2O `1em5` input (about 30.4 million product
determinants), eight host threads, the Thrust backend with `cc120`, NVHPC/HPC-X CUDA 13 `26.3`,
and one MPI rank on the single GB10 GPU. The larger `1em7` case reaches about
98 GB before its first Davidson iteration and is killed by the 128 GB node's
memory limit. `1em5` retains a substantial GPU workload while leaving enough
memory headroom and runtime margin for continuous benchmarking. NCCL is disabled
for the single-GPU case, and all three explicit communicator sizes are one. The
Rikyu rows retain the `1em7` input and validated `1 x 2 x 2` explicit layout;
their remaining rank factor becomes SBD's implicit Hamiltonian communicator.

The R-CCS Cloud GH200 route uses the H2O `1em6` input (about 191 million
product determinants), the Thrust backend with `cc90`, NVHPC/HPC-X CUDA 13
`26.9`, eight host threads, and one MPI rank on its unified Grace Hopper superchip. No Slurm GPU
request is made because `qc-gh200` exposes its single GPU as part of the node.
NCCL is disabled for the single-rank case.

The R-CCS Cloud FX700 route uses the H2O `1em4` input (about 2.38 million
product determinants) with four MPI ranks and 12 OpenMP threads per rank,
bound one rank per A64FX NUMA/CMG domain. SBD requires C++17 features missing
from Fujitsu compiler 4.11.1's bundled libc++, so this route uses the system
GCC 8.5/MPICH stack with 512-bit SVE enabled. It links Fujitsu's optimized
LAPACK and its required runtime libraries by absolute path. The absolute paths
are intentional: adding the Fujitsu library directory with `-L` causes
MPICH's trailing `-lmpi` to resolve to Fujitsu MPI instead, mixing two MPI
implementations in one executable.

The input files are not committed to this repository; `build.sh` stages them
from its `bk_fetch_source` clone of SBD's `data/h2o` directory into `artifacts/`.
`data/h2o/README.md` records the upstream revision, checksums, and Apache-2.0
provenance.

The emitted FOM is SBD's internal Davidson time in seconds. Shell wall time is
not used because MPI startup and scheduler overhead are substantial on RIKYU.
The run is accepted only when its energy matches the established reference for
its selected input within a combined `1e-12 + 1e-11 |E|` tolerance.

The DGX Spark route was validated on `ng-dgx-m1` with NVHPC 26.3 and eight
host threads. The exact energy was `-76.24373504205296 Ha`; the internal
Davidson FOM was `220.402954 s`, the multiply section was `9.990933 s`, and
the complete Slurm job took 3 minutes 59 seconds.

The R-CCS Cloud GH200 route was directly validated on `qc-gh200-01` with
NVHPC 26.9 and eight host threads. The exact energy was
`-76.24377593489787 Ha`; the internal Davidson FOM was `485.725737 s`, the
multiply section was `21.229936 s`, and the complete Slurm job took 8 minutes
53 seconds.

The R-CCS Cloud FX700 route was directly validated with GCC 8.5, MPICH 4.0,
512-bit SVE, and Fujitsu LAPACK. The exact energy was `-76.2429584823075 Ha`;
the internal Davidson FOM was `739.454590 s`, the multiply section was
`33.575472 s`, and the complete Slurm job took 12 minutes 55 seconds.

The Rikyu route was validated with NVHPC 26.3 on project `rkp00012`. All
three rows converged to `-76.243776776861 Ha`:

| B200 GPUs | Nodes | Internal Davidson FOM (s) | 4-GPU-relative speedup |
|---:|---:|---:|---:|
| 4 | 1 | 565.510 | 1.00x |
| 8 | 2 | 290.222 | 1.95x |
| 16 | 4 | 152.144 | 3.72x |

A fresh BenchKit validation rebuilt upstream SBD commit
`9481f290c2f49d4f8e5df9b0c9c87ea0f7937c2c` through `build.sh`, confirmed the
effective `cc100` rank-distributed/index-reordered/NCCL configuration, and
submitted the eight-GPU row through `scripts/test_submit.sh`. The job converged
to `-76.2437767768609 Ha` with a `290.281226 s` internal Davidson FOM, and
`scripts/result.sh` produced valid result JSON with source provenance and the
`mult` timing section. Only this eight-GPU row has been independently re-run
through `test_submit.sh`; the four- and sixteen-GPU rows above have not.


## Flow2 Type I

Flow2_Type1 uses a CPU build with oneAPI 2026.1.0, Intel MPI 2021.18 and MKL. The initial H2O-1em4 case requires one node, four MPI ranks and twelve OpenMP threads per rank. GPU profiling is disabled.

## Camphor3

Camphor3 uses a CPU build with Intel 2023, Intel MPI, and MKL. The
H2O-1em4 case uses one node, four MPI ranks and twelve OpenMP threads
per rank, with MKL limited to one thread. Source and input selection,
calculation parameters, energy comparison, and FOM extraction follow
the existing CPU route. The initial ten-minute configuration uses
site-default memory and is enabled after direct Slurm and Jacamar validation.


## Flow2 Type II CPU execution

The native ARM CPU route uses GNU C++17 through the existing HPC-X MPI
wrapper (`OMPI_CXX=g++`), GNU OpenMP, and NVPL from NVHPC 26.5. CMake 4.4.3
selects NVPL LP64 (32-bit BLAS/LAPACK integers) and sequential BLAS/LAPACK,
keeping threading in SBD's OpenMP regions. The GPU backend, NCCL, cuBLAS,
and NVTX are disabled. MPI/PMIx libraries remain from the same HPC-X
installation; the site's existing UCX is retained.

The normal matrix enables H2O-1em4 on one node with four MPI ranks,
18 OpenMP threads per rank, and a 30-minute limit including compilation.
The site's default queue applies. Validation used t2-debug: MPI/OpenMP,
BLAS/LAPACK numerical probes, and per-rank library selection passed before
SBD completed with energy `-76.2429584823075 Ha` and internal Davidson FOM
`34.293082 s` (one run).

The existing 1x2x2 communicator layout, calculation parameters, energy
reference/tolerance, Davidson FOM, multiply section, toolchain, and both
actual input file records are retained. Input source metadata remains a
staged-file declaration; the observed digests and sizes identify the files
actually used. No GPU profiling is enabled for this CPU route.

## Offline Davidson time-ratio projection

`estimation/aggregate_davidson.py` is an explicit, offline calculation for a
single profiled rank/GPU. It does not run NSYS/NCU, change normal collection,
replace the benchmark FOM, or emit a full Estimate. Use Python 3.11+ on the
estimation host; the script needs only the standard library.

Supply the saved NSYS SQLite, its **raw** outer Davidson NVTX name, parsed
LightGBM 1.1 JSON (`metrics.kernels`), and an explicit sample association:

```sh
python3.11 programs/sbd/estimation/aggregate_davidson.py \
  --nsys-sqlite discovery.sqlite \
  --nvtx-range 'sbdiag.h:461 [diag] : Davidson' \
  --predictions parsed-predictions.json --samples samples.json > davidson-ratio.json
```

Use the raw label from the actual source/trace; its line number can change.
The JSON prediction rows are the common LightGBM parser's output, before any
projection onto an application section. Each row must retain its name,
configuration, source/target GPU, aligned source/predicted nanoseconds and
`sample_count: 1`. A combined document may contain additional rows, but only
the five explicitly associated rows are used.

`samples.json` declares `scope` (`nsys_sha256`, `nvtx_range`, `mpi_size: 1`,
`mpi_rank: 0`), `source_gpu`, `target_gpu`, and five `samples`. Each sample has
`family`, the exact NSYS `kernel_name`, three-dimensional `grid` and `block`
arrays, a zero-based `launch_index` **within that family and Davidson range**,
and a zero-based `prediction_index` in `metrics.kernels`. The required families
are `MultAlphaBeta`, `MultUnified<0,1>`, `MultUnified<1,1>`,
`MultUnified<1,0>` and `MultUnified<0,0>`. Choose one non-first, typical launch
per family. Check the profiler's actual filter/skip and saved metadata when
creating this association: a CSV PID alone is not an MPI rank or a link between
separate profiling runs. This helper validates the declaration against NSYS and
prediction signatures/configurations; it does not verify the raw NCU report.
The 1-rank declaration likewise records a known acquisition condition rather
than inferring the MPI job size from a single profiled PID.

The source trace must have all five families, one signature/Grid/Block per
family, unambiguous launch origins, no kernels crossing the Davidson boundary,
and no kernel/kernel or kernel/transfer overlap. The post-Davidson multiply is
excluded even when it uses the same kernel names. Unsupported traces and
missing/mismatched predictions fail without a ratio; they do not silently use
identity predictions.

For NSYS family totals `K_i`, aligned predicted/source sample ratios `r_i`,
and Davidson wall time `T`, the conditional projected time is:

```text
U = T - sum(K_i)
T' = U + sum(K_i * r_i)
time_ratio_predicted_over_source = T' / T
```

`U` contains unselected kernels, the union of copy/memset events, and GPU-event
gaps. These parts are held unchanged on the target as an explicit assumption.
Host synchronization already overlaps GPU execution and is never added as a
second duration. NCU replay time and sample counts are not NSYS weights.
The output records the terms, coverage, residual components, sample association,
input digests and assumptions. This is a conditional projection, not an accuracy
claim: representative samples, unchanged execution structure/residual time and
target-side overlap remain unvalidated. It does not predict multi-rank MPI or
other ranks and must not be generalized to overlapping GPU workloads.


## Local Davidson Estimate

Run the offline projection through the standard Estimate writer with Python
3.11+ and jq on the estimation host, from the repository root:

```sh
BK_ESTIMATION_PYTHON=python3.11 bash programs/sbd/estimate.sh \
  result.json discovery.sqlite predictions.json samples.json TARGET_SYSTEM \
  > estimate.json
```

Use the prediction and sample formats described above and supply the
corresponding Result explicitly. Check input, source, configuration and profiling
provenance before associating these separate runs. The Result digest is recorded
as provenance; no additional field in `samples.json` is required.
The entry point requires an SBD `davidson_internal_s` Result in seconds with one
node and one MPI rank. It neither fetches inputs nor sends the Estimate.

The current FOM is the original Result FOM; the future FOM is that value times
the NSYS-derived Davidson ratio. NSYS wall time is retained separately in
`measurement`, and the full projection, residual and model provenance are in
`future_system.model`. `input_artifacts` records paths and digests; keep these
files with the Estimate. An existing server Result identity is preserved;
missing server identity is not invented. No post-Davidson `mult` section is
used as a Davidson timing section.

The output is conditional on applying the NSYS range ratio to the internal
Davidson timer, representative samples and unchanged residual/structure.
`performance_ratio` follows the existing Estimate convention (current/future),
which is the inverse of `time_ratio_predicted_over_source`. Unsupported or
incomplete inputs exit unsuccessfully without an Estimate; there is no identity
fallback. Source/target GPU names and the requested target system are recorded
separately. This does not establish target-side accuracy or support multi-rank
scaling.


## Davidson acquisition and the estimation wrapper

For a one-rank GPU run, explicitly enable `BK_SBD_DAVIDSON_PROFILE=true`
in addition to the existing NCU profiling option. This mode requires
`PYTHON_BIN` pointing to Python 3.11+ with sqlite3. It uses the existing
NSYS discovery, selects the unique outer Davidson NVTX range, and samples
the second launch of each of the five families once, using the existing
`detailed`/full-counter preset required by the model. The resulting
`davidson-plan.json` and `discovery.sqlite` stay with the discovery artifacts.
Missing ranges, multiple configurations or unsupported overlap stop this
profile mode; the normal benchmark Result is retained. Existing profiling
without this option is unchanged. No synchronization is added.

On the estimation host, prepare `results/result0.json` and the corresponding
local discovery/NCU artifacts, then use the normal wrapper:

```sh
export BK_SBD_DAVIDSON_PLAN=path/to/discovery/davidson-plan.json
export BK_SBD_DAVIDSON_PROFILES_DIR=path/to/profiles
export BK_GPU_LIGHTGBM_SOURCE_GPU=GB200
export BK_GPU_LIGHTGBM_TARGET_GPU=H100
export BK_ESTIMATION_FUTURE_SYSTEM=H100
export BK_ESTIMATION_PYTHON=python3.11
# Configure the existing LightGBM 1.1 runtime and pinned PerfTools checkout.
export BK_GPU_LIGHTGBM_PERFTOOLS_ROOT=path/to/PerfTools
export BK_GPU_LIGHTGBM_PERFTOOLS_COMMIT=FULL_COMMIT_SHA
export BK_GPU_LIGHTGBM_PYTHON=path/to/model-runtime/python
bash scripts/estimation/run.sh sbd
```

The wrapper mode defaults to no PerfTools fetch. It verifies the selected
plan/metadata, exactly one raw NCU row and full XYZ Grid/Block per family,
then reuses LightGBM conversion/inference, Davidson aggregation and the
standard Estimate writer. It writes `results/estimate_sbd_result0.json`;
component results, sample associations and inference evidence remain under
`results/estimation_artifacts/`. Precomputed or scoped input/archive overrides
are rejected in this mode. Missing or mismatched inputs fail without an
Estimate or identity fallback. Existing offline five-argument usage remains
available.

Supply the bundle for this Result explicitly; matching names or a digest do
not establish scientific equivalence between separate runs. The one-rank
Result condition is checked, and the bundle must have been acquired with that
condition. The existing conditional projection and residual/representative
sample assumptions still apply. This interface does not schedule GPU work,
configure server retrieval, or submit an Estimate.

### RIKYU single-rank Davidson collection

The 1-node, 1-rank, 8-thread row uses H2O 1em4 and task/adet/bdet
communication sizes 1/1/1. Existing 4-rank-per-node rows retain H2O 1em7
and 1/2/2. The single-rank recipe selects the existing Davidson NSYS/NCU
collection (five kernel families, one launch each); it requires Python 3.11+
with sqlite3 and defaults to `python3.12`. Set `PYTHON_BIN` for another
installed interpreter, `BK_SBD_DAVIDSON_PROFILE=false` for the previous
profile selection, or `SBD_PROFILER_TOOL=none` to disable profiling.
RIKYU builds use two compiler processes by default; override with
`CMAKE_BUILD_PARALLEL_LEVEL`. GPU validation of this normal build/run recipe
is pending; prior single-rank validation used a separate build/launch driver.
