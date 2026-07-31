# SBD benchmark

This BenchKit application runs the NVIDIA Thrust TPB selected-basis
diagonalization benchmark from `github.com/r-ccs-cms/sbd`.

The RIKYU recipe uses the H2O cc-pVDZ FCIDUMP with the `1em7` selected alpha
determinant file (about 628 million product determinants), one MPI rank per
B200 GPU, and the rank-distributed/index-reordered/NCCL build configuration
validated in the SubWG2 benchmark study. The inputs are included under
`programs/sbd/data/h2o/` and can be overridden with `BK_SBD_INPUT_DIR` when a
project-storage copy is preferred.

The DGX Spark route uses the same input and Thrust backend with `cc120`,
NVHPC/HPC-X CUDA 13 `26.3`, and one MPI rank on the single GB10 GPU. NCCL is
disabled for that single-GPU case.

The input files are copied unchanged from SBD's tracked `data/h2o` directory;
`data/h2o/README.md` records the upstream revision, checksums, and Apache-2.0
provenance.

The emitted FOM is SBD's internal Davidson time in seconds. Shell wall time is
not used because MPI startup and scheduler overhead are substantial on RIKYU.
