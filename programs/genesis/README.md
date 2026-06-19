# GENESIS BenchKit Integration Notes

This directory owns GENESIS-specific build, run, profiler, and estimation
settings. Shared BenchKit CI and estimation packages should not depend on the
environment variables documented here. They are local conveniences for
`programs/genesis/*.sh` only; the app wrapper passes information to the shared
layers through common artifacts such as `results/result`, `SECTION:` metadata,
and `padata*.tgz`.

## GH200 GPU Run And NCU Collection

For MiyabiG and RC_GH200, `run.sh` first runs GENESIS without a profiler and
uses that run to measure the app FOM and section timings. It then runs
additional NCU acquisition passes by default; those passes are used only to
derive GPU kernel source/target time ratios for estimation. Set
`BK_GENESIS_NCU_PROFILE=false` or `GENESIS_PROFILER_TOOL=none` to skip the
additional profiler runs.

The current GENESIS wrapper can collect multiple NCU windows as separate
archives:

```text
results/padata_inter.tgz
results/padata_intra.tgz
results/padata_pairlist.tgz
```

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

## Estimation Sections

GENESIS treats the log `dynamics` time as the FOM. The current wrapper maps the
log into section metadata in `programs/genesis/estimate.sh`.

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

GENESIS chooses GPU section packages inside `programs/genesis/estimate.sh`.
Shared BenchKit code and section packages must not depend on these variables.

Single-package selection:

```bash
BK_GENESIS_GPU_SECTION_PACKAGE=gpu_kernel_mlp_v15
# or
BK_GENESIS_GPU_SECTION_PACKAGE=gpu_kernel_lightgbm_v10
```

Multiple-package comparison:

```bash
BK_GENESIS_GPU_SECTION_PACKAGES=gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15
```

When multiple packages are selected, the app wrapper asks for
`gpu_kernel_ensemble_average`, and passes the candidate packages through common
section metadata. The ensemble package does not know this is GENESIS-specific.

Current GPU section/artifact mapping:

```text
pairlist       -> results/padata_pairlist.tgz -> build_pairlist
pme_real_inter -> results/padata_inter.tgz    -> force_inter_cell
pme_real_intra -> results/padata_intra.tgz    -> force_intra_cell
```

The app wrapper passes kernel selectors to GPU section packages through generic
selector variables:

```bash
BK_GPU_KERNEL_SECTION_PAIRLIST_REGEX=build_pairlist
BK_GPU_KERNEL_SECTION_PME_REAL_INTER_REGEX=force_inter_cell
BK_GPU_KERNEL_SECTION_PME_REAL_INTRA_REGEX=force_intra_cell
```

NCU archives contain sampled kernel launches, not full application section
timings. The GPU section packages compute source/target kernel time ratios from
these samples. Those ratios are applied to app-side section times measured from
the profiler-free GENESIS run.

## Site-Specific Build/Run Overrides

These variables are app-local knobs consumed by `programs/genesis/build.sh` and
`programs/genesis/run.sh`.

```bash
GENESIS_MIYABIG_MODULE
GENESIS_GH200_MODULE
GENESIS_MIYABIG_CUDA_PATH
GENESIS_MIYABIG_FC
GENESIS_MIYABIG_CC
GENESIS_MIYABIG_CONFIG_ARGS
GENESIS_MIYABIG_PROFILER_TOOL
GENESIS_GH200_PROFILER_TOOL
GENESIS_MIYABIG_PROFILER_LEVEL
GENESIS_GH200_PROFILER_LEVEL
GENESIS_PROFILER_TOOL
GENESIS_PROFILER_LEVEL
```

`GENESIS_*_PROFILER_TOOL=ncu` requests additional NCU acquisition. `none`
disables it explicitly.
