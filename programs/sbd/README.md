# SBD benchmark

This BenchKit application runs the NVIDIA Thrust TPB selected-basis
diagonalization benchmark from `github.com/r-ccs-cms/sbd`.

The RIKYU recipe uses the H2O cc-pVDZ FCIDUMP with the `1em7` selected alpha
determinant file (about 628 million product determinants), one MPI rank per
B200 GPU, and the rank-distributed/index-reordered/NCCL build configuration
validated in the SubWG2 benchmark study. The inputs are included under
`programs/sbd/data/h2o/` and can be overridden with `BK_SBD_INPUT_DIR` when a
project-storage copy is preferred.

The DGX Spark route uses the H2O `1em5` input (about 30.4 million product
determinants), the Thrust backend with `cc120`, NVHPC/HPC-X CUDA 13 `26.3`,
and one MPI rank on the single GB10 GPU. The larger `1em7` case reaches about
98 GB before its first Davidson iteration and is killed by the 128 GB node's
memory limit. `1em5` retains a substantial GPU workload while leaving enough
memory headroom and runtime margin for continuous benchmarking. NCCL is disabled
for the single-GPU case, and all three explicit communicator sizes are one. The
Rikyu rows retain the `1em7` input and validated `1 x 2 x 2` explicit layout;
their remaining rank factor becomes SBD's implicit Hamiltonian communicator.

The input files are copied unchanged from SBD's tracked `data/h2o` directory;
`data/h2o/README.md` records the upstream revision, checksums, and Apache-2.0
provenance.

The emitted FOM is SBD's internal Davidson time in seconds. Shell wall time is
not used because MPI startup and scheduler overhead are substantial on RIKYU.
The run is accepted only when its energy matches the established reference for
its selected input within a combined `1e-12 + 1e-11 |E|` tolerance.

The DGX Spark route was validated on `ng-dgx-m2` with NVHPC 26.3. The exact
energy was `-76.24373504205295 Ha`; the internal Davidson FOM was
`228.928853 s`, and the complete Slurm job took 4 minutes 9 seconds.

The Rikyu route was validated with NVHPC 26.3 on project `rkp00012`. All
three rows converged to `-76.243776776861 Ha`:

| B200 GPUs | Nodes | Internal Davidson FOM (s) | 4-GPU-relative speedup |
|---:|---:|---:|---:|
| 4 | 1 | 565.510 | 1.00x |
| 8 | 2 | 290.222 | 1.95x |
| 16 | 4 | 152.144 | 3.72x |

A fresh BenchKit validation rebuilt upstream SBD commit
`1470aac99597e882612f99009d29b6a20fdd69af` through `build.sh`, confirmed the
effective `cc100` rank-distributed/index-reordered/NCCL configuration, and
started the four-GPU `run.sh` row with the expected energy trajectory. That
repeat run was intentionally canceled after Davidson restart `1.0`, at energy
`-76.24377677424239 Ha`, once the build, launcher, GPU mapping, and numerical
path had all been reconfirmed.
