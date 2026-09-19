# Patches

Applied by `build.sh` only when the fix is not already present in the
fetched source (grep-guarded), so they become no-ops once upstream
merges them. Both originate from `william-dawson/MHDTurbulence`
branch `gfortran-port` (candidate upstream PRs):

- `random_seed_put_size.patch` — commit `d9a19d9`: `random_seed(PUT=)`
  requires the array to match the compiler's seed size (8 for gfortran);
  the shipped size-2 array breaks strict compilers. Physically inert
  (the seeded RNG feeds a disabled perturbation, `rrv=0`).
- `acc_init_before_mpi.patch` — commit `4db3adb`: initialize the CUDA
  context before `MPI_Init`. Without it, multi-node runs hang silently
  in the first `BoundaryCondition` (UCX "cannot find remote protocol"
  on the device-buffer `MPI_ISEND`, then `MPI_WAITALL` on a dead
  request; the app's `MPI_ERRORS_RETURN` handler means the failed ISEND
  returns an error code that is never checked).

Launch side (in `run.sh`, RIKYU case): each rank pins one GPU via
`CUDA_VISIBLE_DEVICES=$OMPI_COMM_WORLD_LOCAL_RANK`; combined with the
patch this is required for multi-node GPU runs. Validated 2026-09-03 on
Rikyu (8 GPUs / 2 nodes, results bit-consistent with 1-GPU runs).
