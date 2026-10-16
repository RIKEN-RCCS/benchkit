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


## Flow2 Type II preparation

The proposed native ARM CPU route uses GNU C++17 through the existing
HPC-X MPI wrapper (`OMPI_CXX=g++`), GNU OpenMP, and NVPL from NVHPC 26.5.
CMake 4.4.3 selects NVPL LP64 (32-bit BLAS/LAPACK integers) and sequential
BLAS/LAPACK, keeping threading in SBD's OpenMP regions. The GPU backend,
NCCL, cuBLAS, and NVTX are disabled. MPI/PMIx libraries remain from the same
HPC-X installation; the site's existing UCX is retained.

The initial H2O-1em4 validation plan uses t2-debug, one node, four MPI ranks
and 18 OpenMP threads per rank, with a 30-minute limit including compilation.
A native MPI/OpenMP and BLAS/LAPACK numerical probe must pass before SBD.
Retain the established 1x2x2 communicator layout, calculation parameters,
energy reference/tolerance, Davidson FOM, multiply section, toolchain and
both actual input file records. The normal matrix row remains disabled
until native compilation and numerical validation succeed.
