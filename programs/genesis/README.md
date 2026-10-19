# GENESIS Benchkit Integration Notes

This directory owns GENESIS-specific build, run, profiler, and estimation
settings. Shared Benchkit CI and estimation packages should not depend on the
environment variables documented here. They are local conveniences for
`programs/genesis/*.sh` only; the app wrapper passes information to the shared
layers through common artifacts such as `results/result`, `SECTION:` metadata,
and `padata*.tgz`.

## NVIDIA GPU Run And NCU Collection

For NVIDIA GPU systems, `run.sh` first runs GENESIS without a profiler and
uses that run to measure the app FOM and section timings. It then runs
additional NCU acquisition passes by default; those passes are used only to
derive GPU kernel source/target time ratios for estimation. MiyabiG and
RC_GH200 default to manual NCU windows, while RIKYU defaults to automatic NSYS
discovery followed by NCU. Set
`BK_PROFILER=none`, `BK_GENESIS_NCU_PROFILE=false`, or
`GENESIS_PROFILER_TOOL=none` to skip the additional profiler runs.

The preferred profiler control variables are shared across applications:

```bash
BK_PROFILER=ncu          # none|fapp|ncu
BK_PROFILER_LEVEL=detailed
```

GENESIS still accepts the app/site-specific overrides below for compatibility
and site-local tuning; they override the generic variables when set.

RIKYU is a GB200 system. The default GENESIS RIKYU build path uses the current
site development SIF image because it provides CUDA, GNU compilers,
GNU-compatible Open MPI Fortran modules, and Nsight tools:

```bash
GENESIS_RIKYU_SIF=/shared/software/hpc-dev-container/hpc_dev.sif
GENESIS_RIKYU_COMPILER_FAMILY=gnu
GENESIS_RIKYU_GPU_ARCH=sm_100
```

The RIKYU SIF image name, path, and contents are still site-local and may
change. Set `GENESIS_RIKYU_SIF` to override the image path. Set
`GENESIS_RIKYU_APPTAINER` to override the Apptainer command and
`GENESIS_RIKYU_APPTAINER_BINDS` to add comma-separated bind mounts. The CI
runner environment is expected to make `apptainer` available on `PATH`.

The RIKYU run path keeps the benchmark at the p8 default size and launches the
container per rank from inside the Slurm allocation:

```bash
srun --mpi=pmix -n 8 --ntasks-per-node=4 apptainer exec --nv ... ./spdyn p8.inp.sub
```

`PMIX_MCA_gds=hash` is set by default for RIKYU because the containerized
Open MPI runtime otherwise fails to read Slurm PMIx shared-memory state on
multi-node p8 runs. RIKYU follows the same default additional NCU acquisition
policy as the other NVIDIA GPU systems; set `BK_PROFILER=none` or
`GENESIS_RIKYU_PROFILER_TOOL=none` to run without profiling.

The common acquisition workflow collects multiple NCU windows as separate
archives in unique `results/profile_<id>/` directories. GENESIS supplies kernel
selectors, sections, and host/container launch builders, not output paths.

The default profile names are:

```bash
BK_GENESIS_NCU_PROFILE=true
BK_GENESIS_NCU_PROFILE_NAMES="inter intra pairlist"
```

The default kernel filters and windows are:

```bash
BK_GENESIS_NCU_INTER_KERNEL_REGEX='regex:.*force_inter_cell.*'
BK_GENESIS_NCU_INTER_LAUNCH_SKIP=100
BK_GENESIS_NCU_INTRA_KERNEL_REGEX='regex:.*force_intra_cell.*'
BK_GENESIS_NCU_INTRA_LAUNCH_SKIP=100
BK_GENESIS_NCU_PAIRLIST_KERNEL_REGEX='regex:.*build_pairlist.*'
BK_GENESIS_NCU_PAIRLIST_LAUNCH_SKIP=10
BK_GENESIS_NCU_LAUNCH_COUNT=10
BK_GENESIS_NCU_PAIRLIST_LAUNCH_COUNT=10
BK_GENESIS_NCU_NSTEPS=600
```

`BK_GENESIS_NCU_NSTEPS` shortens only the additional NCU acquisition input. The
unprofiled benchmark run keeps the original input and remains the source of FOM
and section timing. Use `BK_GENESIS_NCU_NSTEPS=off` when the full input should be
used for NCU as well.

The wrapper also accepts per-profile overrides:

```bash
BK_GENESIS_NCU_<PROFILE>_KERNEL_REGEX
BK_GENESIS_NCU_<PROFILE>_LAUNCH_SKIP
BK_GENESIS_NCU_<PROFILE>_LAUNCH_COUNT
BK_GENESIS_NCU_<PROFILE>_NSTEPS
```

Legacy single-window collection can be requested with `BK_GENESIS_NCU_KERNEL_REGEX`;
the wrapper treats it as a `custom` profile.

RIKYU's default automatic mode derives candidate NCU windows from an Nsight
Systems CUDA kernel summary and then executes the generated NCU plan:

```bash
BK_GENESIS_NCU_PROFILE_MODE=discovery
```

When `BK_GENESIS_NCU_PROFILE_MODE=discovery`, `run.sh` keeps the normal
unprofiled benchmark run, then runs a short NSYS discovery pass, writes
discovery and plan JSON in a common-owned workspace, and runs the
selected NCU windows. The generated NCU profiles default to the top three
GPU-time kernels with `launch_skip=1` and `launch_count=10`; the NCU archives
are registered as section artifacts and are used by the GPU estimation packages
to compute source/target kernel time ratios.

Use `BK_GENESIS_NCU_PROFILE_MODE=discovery-only` when investigating NSYS output
without paying the NCU cost. That mode writes the full discovery summary and
plan but skips NCU collection. If the NSYS CSV has already been created by
site-local tooling, set
`BK_GENESIS_NCU_DISCOVERY_CSV=/path/to/cuda_gpu_kern_sum.csv` to skip the NSYS
pass and only generate the NCU plan. Manual mode still uses the configured
`inter intra pairlist` windows above.

## Estimation Sections

GENESIS treats the log `dynamics` time as the FOM. The app-side parser
`programs/genesis/parse_timing.sh` maps a GENESIS log and dynamics FOM into
section/overlap timing rows. This parser is not estimation-specific; it can be
used from `run.sh`, `estimate.sh`, or local diagnostics.

`estimate.sh` should stay limited to GENESIS-owned decisions: section names,
how to extract section timings from the GENESIS log, and which section package
each section should use. Package loading, fallback, FOM composition, and
Estimate JSON construction are handled by the shared Benchkit estimation layer.

Current section names are:

```text
pairlist
bond
angle
dihedral
pme_real_wait
pme_real_inter
pme_real_intra
pme_recip
integrator
other
```

`other` is a positive residual used to reconstruct `dynamics` from the measured
sections. If a simple sum exceeds `dynamics`, the wrapper emits an additional
overlap instead of a negative residual.

`pme real` and `pme recip` are modeled as overlapping parts of `nonbond`. The
wrapper emits an overlap for:

```text
pme_real_wait,pme_real_inter,pme_real_intra,pme_recip
```

The current temporary split for `pme real` is:

```text
pme_real_wait  = pme real * 0.8  # wait / CPU / communication-like part
pme_real_inter = pme real * 0.1  # GPU inter-cell kernel family
pme_real_intra = pme real * 0.1  # GPU intra-cell kernel family
```

The fractions are app-local knobs:

```bash
BK_GENESIS_PME_REAL_IDENTITY_FRACTION
BK_GENESIS_PME_REAL_INTER_FRACTION
BK_GENESIS_PME_REAL_INTRA_FRACTION
```

The current side uses a Fugaku baseline FOM with weak scaling. The MiyabiG
section breakdown is used only for the future-side projection toward
FugakuNEXT.

## GPU Section Package Mapping

GENESIS does not choose individual GPU estimator packages. It marks GPU-related
sections as `gpu_kernel_ensemble_average`; the common section package decides
which concrete GPU estimator packages to run. This keeps GENESIS-side ownership
limited to app concepts: section names, timing extraction, launch conditions,
and kernel selectors.

Benchkit operators can override the concrete GPU estimator package set with the
generic `BK_GPU_KERNEL_ENSEMBLE_PACKAGES` variable when needed. That knob is not
GENESIS-specific and should not be required for normal GENESIS maintenance.

Current GPU section/kernel mapping:

```text
pairlist       -> build_pairlist
pme_real_inter -> force_inter_cell
pme_real_intra -> force_intra_cell
```

Common acquisition registers archives and metadata against the originating
execution and section. `scripts/result.sh` attaches them to
`fom_breakdown.sections[].artifacts[]` in the Result JSON, regardless of whether
profiling ran before or after section emission. `estimate.sh`
consumes that Result JSON; it should not infer profiler output paths by scanning
the filesystem or by knowing profiler archive names.

The app wrapper passes kernel selectors to GPU section packages through the
common estimation helper. These selectors are GENESIS-owned because they name
GENESIS kernels.

NCU archives contain sampled kernel launches, not full application section
timings. The GPU section packages compute source/target kernel time ratios from
these samples. Those ratios are applied to app-side section times measured from
the profiler-free GENESIS run.

## Agent-Assisted Estimation Method Version Review

When an agent changes either GENESIS method file, it should run this tool before
reporting the change ready for review, as described in [AGENTS.md](AGENTS.md).
The user need not remember to invoke it separately. With Python 3.12+ and Git,
compare the two method files in the working tree against an existing local
target commit or ref:

```bash
python3.12 scripts/check_estimation_version.py --app genesis --base refs/remotes/origin/develop
```

`--app` is required and selects only `programs/<app>/estimate.sh` and
`programs/<app>/estimate.metadata.json`; applications are not scanned automatically.
The default base is `HEAD`. Staged and unstaged edits are included. If
`estimate.sh` contents changed but `estimate.metadata.json` has the same
nonempty string `version`, the tool asks whether a version update is needed.
Comment/formatting edits may need no bump; this is a human decision. A changed
version is reported as changed, without ordering version strings. Missing or
invalid files/versions are reported as unknown.

Only those two files are inspected: source dependencies, observation definitions
and shared package changes are outside this check. This manual tool neither
fetches Git objects nor changes files, runs estimation, or connects to a server.
Review/unknown messages return zero; an unavailable base or unsupported partial
clone is a comparison error. No CI gate or automatic version update is added.
The agent reports the output and the reason for updating or keeping the version;
a zero exit status alone does not mean that no review is needed.

## Site-Specific Build/Run Overrides

These variables are app-local knobs consumed by `programs/genesis/build.sh` and
`programs/genesis/run.sh`.

```bash
GENESIS_MIYABIG_MODULE
GENESIS_GH200_MODULE
GENESIS_RIKYU_MODULE
GENESIS_MIYABIG_CUDA_PATH
GENESIS_RIKYU_CUDA_PATH
GENESIS_MIYABIG_FC
GENESIS_MIYABIG_CC
GENESIS_RIKYU_FC
GENESIS_RIKYU_CC
GENESIS_RIKYU_CXX
GENESIS_RIKYU_F77
GENESIS_MIYABIG_CONFIG_ARGS
GENESIS_RIKYU_CONFIG_ARGS
GENESIS_RIKYU_COMPILER_FAMILY
GENESIS_RIKYU_GPU_ARCH
GENESIS_MIYABIG_PROFILER_TOOL
GENESIS_GH200_PROFILER_TOOL
GENESIS_RIKYU_PROFILER_TOOL
GENESIS_MIYABIG_PROFILER_LEVEL
GENESIS_GH200_PROFILER_LEVEL
GENESIS_RIKYU_PROFILER_LEVEL
GENESIS_RIKYU_MPI_CMD
GENESIS_RIKYU_MPI_ARGS
GENESIS_PROFILER_TOOL
GENESIS_PROFILER_LEVEL
```

`GENESIS_*_PROFILER_TOOL=ncu` requests additional NCU acquisition. `none`
disables it explicitly. Prefer `BK_PROFILER` / `BK_PROFILER_LEVEL` for new
generic CI/profile control unless a site needs a GENESIS-specific override.

## Camphor3 CPU Run

Camphor3 uses `PrgEnvIntel/2023`, Intel MPI, MKL, and a mixed-precision CPU
build with AVX-512. The existing p8 input has a 2×2×2 domain decomposition,
so it requires eight MPI ranks. The initial one-node configuration uses
14 OpenMP threads per rank, with a ten-minute scheduler limit and the
site default memory allocation. This configuration is enabled in `list.csv`.

`GENESIS_INPUT_BRANCH` and `GENESIS_INPUT_COMMIT` select the benchmark input
checkout independently of `GENESIS_BRANCH` and `GENESIS_SOURCE_COMMIT` for
the application source. Input selection preserves the build source record.
The benchmark retains its original 6000 steps and scientific parameters.

The CPU run checks that all energy output rows are finite, the final step
matches the input, and the dynamics time is positive. These are completion
checks. Numerical accuracy is checked separately using upstream regression
tests and their reference outputs and tolerances. Run both through the
scheduler on compute nodes.


## Flow2 Type I CPU preparation

Flow2_Type1 uses Intel MPI 2021.18 and oneAPI 2026.1.0 (mpiifx/mpiicx), with the upstream automatic SIMD selection. The original p8 input requires eight MPI ranks; the initial share plan is eight ranks with six threads each. Run the upstream numerical regression cases before the unchanged p8 benchmark.


## Flow2 Type II CPU execution

Flow2_Type2 uses NVHPC 26.5 and the site's existing HPC-X stack for a
native ARM CPU build with MPI/OpenMP, mixed precision, automatic SIMD
selection, and LAPACK disabled. The normal matrix enables one node with
eight MPI ranks, nine threads each, and a 30-minute build/run limit. The
site's default queue applies; validation used t2-debug.

Configure patches recognize nvfortran and remove obsolete PGI/x86 options.
Explicit `FFLAGS` and `FCFLAGS` preserve `-O2 -mp -Mflushz` through upstream
configure. The build checks generated Makefiles and actual Fortran compile
commands and retains the compilation log.

The environment helper uses the module's `OMPI_HOME` to select matching
MPI/PMIx and companion libraries and set Open MPI, PRRTE, and PMIx prefixes.
Source it after loading modules for build, upstream regression, and p8. This
avoids mixing a system PMIx with HPC-X libraries sharing the same SONAME.

Validation with the existing UCX passed an eight-rank MPI probe, the upstream
`test_spdyn/jac_param27/PME_autoselect` and
`test_spdyn/dppc/VRES_NPT_BUSSI_group8` reference checks, and then the unchanged
p8 input (2x2x2 domains, 6000 steps). The run records FOM and the digests and
sizes of the six actual input files; p8 completion checks are separate from
the upstream numerical reference comparisons.

With the site's existing UCX, MPI initialization can set the IEEE invalid
flag, which GENESIS reports at normal termination. This warning did not fail
the validated reference checks, p8 completion, or job exit status. The
upstream UCX fix is tracked in
[openucx/ucx#11672](https://github.com/openucx/ucx/pull/11672).
The normal route retains the site's UCX and does not suppress or clear IEEE
flags.
