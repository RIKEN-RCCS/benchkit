# SALMON GENOA / FX700 Handoff

This note is for an on-site agent continuing the SALMON integration work.

## Scope and rules

- Treat GENOA and FX700 as separate platform configurations. Do not infer MPI or network behavior from the CPU/compiler family.
- Keep platform-specific settings in `programs/salmon/build.sh` and `programs/salmon/run.sh`.
- Do not change the SALMON input archive or rewrite `theory` values unless the site owner confirms that the archive is wrong.
- Do not mark a run successful only because the launcher returned zero. Check the application output and the GS-to-RT restart state.
- Use WSL Ubuntu-22.04 for repository checks: `bash -n`, `shellcheck`, `git diff`, and patch validation. Use the target site for module, compiler, MPI, and runtime checks.
- Do not remove existing platform branches or comments without confirming the platform-specific behavior with the site owner.
- Commits must use `git commit --signoff` and explain the platform-specific reason. Do not push unrelated temporary files or generated SALMON sources.

## Current repository state

The current branch contains:

- `b35f4fd`: SALMON Fujitsu topology guard patch and GENOA OpenMPI selection.
- `5f99c5d`: GENOA AOCL utility dependency detection and linking.

The untracked `.tmp-salmon-v222-check/` directory is only a local validation checkout and must not be committed.

## GENOA

### Expected platform configuration

BenchPark's GENOA definition uses:

- module: `system/genoa mpi/openmpi-x86_64`
- MPI: OpenMPI, currently `/usr/lib64/openmpi`
- compiler: GCC
- BLAS/LAPACK baseline: OpenBLAS
- scheduler setting: `SLURM_MPI_TYPE=pmix`

The previous GENOA failure used `/usr/lib64/mpich/bin/mpicc` and `mpif90`; that was a configuration mismatch. The build configuration has been changed to OpenMPI.

### AOCL configuration

The site AOCL installation is expected under:

```text
/lvs0/rccs-nghpcadu/nakamura/aocl/install/
```

Relevant libraries are:

```text
amd-blis/lib/LP64/libblis-mt.so
amd-libflame/lib/LP64/libflame.so
amd-utils/lib/libaoclutils.so
amd-utils/lib/libau_cpuid.so
```

The build script searches the AOCL root for the two utils libraries, adds their directory to `LD_LIBRARY_PATH`, and passes them with BLIS and libFLAME. The earlier linker failure was caused by missing `libaoclutils.so` and `au_cpuid_has_flags`.

### Important pending check

Verify `programs/salmon/run.sh` uses the same OpenMPI module as `build.sh`. A runtime branch still needs to be checked for an old MPICH module reference. Build and run must use the same MPI family.

### GENOA completion criteria

- Configure reports `/usr/lib64/openmpi/bin/mpicc` and `/usr/lib64/openmpi/bin/mpif90`.
- AOCL configure/link output contains BLIS, libFLAME, `libaoclutils.so`, and `libau_cpuid.so`.
- SALMON builds without undefined AOCL symbols.
- GS and RT both complete with finite values and valid restart files.
- The result contains valid `gs` and `rt` sections.

## FX700

### Expected platform configuration

- module: `system/fx700 FJSVstclanga`
- launcher/compiler: Fujitsu MPI wrappers `mpifcc` / `mpifrt`
- run shape for the current test: `1 MPI process x 48 OpenMP threads`
- `SLURM_MPI_TYPE=pmix`
- BLAS/LAPACK: `-SSL2BLAMP`

The Fujitsu topology patch is applied to SALMON v2.2.2, but `USE_FJMPI=OFF` is used for FX700. The patch separates the Fujitsu compiler macro from the Tofu-specific topology path. Do not turn `USE_FJMPI` on for FX700 without site confirmation.

### Observed FX700 behavior

- Build succeeds with `1 MPI x 48 threads`.
- GS reaches `end SALMON`.
- RT starts but reports `rbox1=0` and `Ne=NaN` at the first time step.
- `run.sh` may also report a missing success marker because the output uses `end SALMON` rather than the current elapsed-time pattern.

Do not solve this by accepting `end SALMON` alone. First establish why the RT restart/input state is invalid. Compare the input namelist, `restart/` files, and GS-to-RT handoff with a successful GH200 run.

### FX700 investigation sequence

1. Confirm the checkout contains the current branch commit and the Fujitsu topology patch.
2. Confirm the build uses `mpifcc` / `mpifrt` from `FJSVstclanga`.
3. Run GS and record the exit status, final output, and all generated restart files with sizes.
4. Confirm `data_for_restart` is moved to `restart` before RT.
5. Compare `Si-1-1-1-tddft.nml`, restart filenames, and working-directory contents with GH200.
6. Run RT separately if needed and inspect the first occurrence of `NaN`, `rbox1`, and `Ne`.
7. Only after valid GS/RT output exists, adjust the success-marker logic to recognize the platform's actual completion marker.

## Required evidence for a change

Record the following in the handoff or pull request:

- system and queue
- module list and `which mpicc mpif90 mpiexec`
- MPI/compiler versions
- SALMON source tag and commit
- node/process/thread shape
- relevant configure summary
- relevant build or run error
- GS/RT output and restart file listing
- whether the result sections were emitted

Run repository checks in WSL before committing:

```bash
bash -n programs/salmon/build.sh programs/salmon/run.sh
shellcheck -S error programs/salmon/build.sh programs/salmon/run.sh
```

Do not combine a GENOA MPI/AOCL fix with an FX700 runtime fix in one commit unless both are independently verified.
