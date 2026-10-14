# MHDTurbulence

Camphor3 builds the upstream `src_f90_omp_host` CPU implementation using
`PrgEnvIntel/2023` and `mpiifx`. The upstream compile-time KH configuration
and initial conditions are preserved and recorded under
`artifacts/mhd_cpu_input`. No external input dataset is required.

The current configuration uses a 300 × 300 × 10 grid, a 4 × 12 × 2 MPI
decomposition (96 ranks), and physical end time 3.0. The initial Camphor3
configuration is one node, 96 MPI ranks, one OpenMP thread per rank, and a
thirty-minute limit with site-default memory. It remains disabled pending
Jacamar validation.

The run consumes artifacts independently of the source checkout and saves
its log, diagnostics, and snapshots under `results/mhd_run`. Like the
existing MiyabiC entrypoint, it requires successful command execution and
available simulation-time and time-per-cell values before emitting results.
FOM retains cell updates per second, and the total section retains the
simulation loop time.

The upstream `RealTimeAnalysis` diagnostic output and documented KH growth
comparison are available for application-level review. An automated
numerical pass/fail check is not invoked by this entrypoint.
