# MHDTurbulence

Camphor3 builds the upstream `src_f90_omp_host` CPU implementation using
`PrgEnvIntel/2023` and `mpiifx`. The upstream compile-time KH configuration
and initial conditions are preserved and recorded under
`artifacts/mhd_cpu_input`. No external input dataset is required.

The current configuration uses a 300 × 300 × 10 grid, a 4 × 12 × 2 MPI
decomposition (96 ranks), and physical end time 3.0. The initial Camphor3
configuration is one node, 96 MPI ranks, one OpenMP thread per rank, and a
ten-minute limit with site-default memory. It remains disabled pending
compute-node validation.

The run consumes artifacts independently of the source checkout and saves
its log, diagnostics, and snapshots under `results/mhd_run`. Completion
checks require the finish marker, reaching the configured physical end time
within the step limit, finite positive timing, and finite initial/final
diagnostics. These checks do not establish numerical accuracy; the upstream
KH growth curve is an empirical comparison metric, not an exact reference
with a published acceptance tolerance. FOM retains cell updates per second,
and the total section retains the simulation loop time.
