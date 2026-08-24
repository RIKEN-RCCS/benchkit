# SBD benchmark

This BenchKit application runs the NVIDIA Thrust TPB selected-basis
diagonalization benchmark from `github.com/r-ccs-cms/sbd`.

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
determinants), the Thrust backend with `cc120`, NVHPC/HPC-X CUDA 13 `26.3`,
and one MPI rank on the single GB10 GPU. The larger `1em7` case reaches about
98 GB before its first Davidson iteration and is killed by the 128 GB node's
memory limit. `1em5` retains a substantial GPU workload while leaving enough
memory headroom and runtime margin for continuous benchmarking. NCCL is disabled
for the single-GPU case, and all three explicit communicator sizes are one. The
Rikyu rows retain the `1em7` input and validated `1 x 2 x 2` explicit layout;
their remaining rank factor becomes SBD's implicit Hamiltonian communicator.

The R-CCS Cloud GH200 route uses the H2O `1em6` input (about 191 million
product determinants), the Thrust backend with `cc90`, NVHPC/HPC-X CUDA 13
`26.3`, and one MPI rank on its unified Grace Hopper superchip. No Slurm GPU
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

The DGX Spark route was validated on `ng-dgx-m2` with NVHPC 26.3. The exact
energy was `-76.24373504205295 Ha`; the internal Davidson FOM was
`228.928853 s`, and the complete Slurm job took 4 minutes 9 seconds.

The R-CCS Cloud GH200 route was directly validated on `qc-gh200-01` with
NVHPC 26.3. The exact energy was `-76.24377593489788 Ha`; the internal
Davidson FOM was `520.734720 s`, the multiply section was `22.730310 s`, and
the complete Slurm job took 9 minutes 34 seconds.

The R-CCS Cloud FX700 route was directly validated on `fx29` with GCC 8.5,
MPICH 4.0, 512-bit SVE, and Fujitsu LAPACK. The exact energy was
`-76.2429584823075 Ha`; the internal Davidson FOM was `747.636165 s`, the
multiply section was `33.897903 s`, and the complete Slurm job took 13 minutes
3 seconds.

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
