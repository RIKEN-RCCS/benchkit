# SCALE-LETKF on RIKYU

The RIKYU route builds the public SCALE-LETKF source with NVHPC and runs the
existing SC23 128x128, two-member benchmark. It uses four ranks for pp and
12 ranks for init, SCALE and LETKF, one CPU thread per rank. Twelve ranks share
one GPU through a job-owned CUDA MPS instance.

The existing `list.csv` requests one launch task with 32 CPUs, reserving one
GPU through the standard RIKYU scheduler template. The app subdivides these
CPUs into the MPI layout above, leaving headroom for MPI and MPS. Inside that
allocation, invoke:

```bash
bash programs/scale-letkf/run.sh RIKYU 1 1 32
```

The arguments describe the outer allocation; the Result records the actual
SCALE/LETKF layout of 12 MPI ranks and one thread per rank. No separate resource
configuration is needed. RIKYU currently permits up to 32 CPUs per GPU;
the allocation also uses the site's default GPU memory reservation.

Build and compute hosts need the same NVHPC/MPI module (default
`nvhpc-hpcx/26.3`), compatible NetCDF C and NVHPC-built NetCDF Fortran, and the
SDK BLAS/LAPACK. Python 3 prepares the namelists; it is an app dependency.
Configure `SCALE_LETKF_NC_CONFIG` and `SCALE_LETKF_NF_CONFIG` with their
`nc-config` and `nf-config` paths, or provide them on PATH. Optional controls
are `SCALE_LETKF_MODULE`, `SCALE_LETKF_MATHLIB_LIBS`,
`SCALE_LETKF_BUILD_JOBS` (default 4), `SCALE_LETKF_BRANCH` and
`SCALE_LETKF_SOURCE_COMMIT`.

The build selects the Blackwell `cc100` target and records the source
adjustment that compiles `mod_mkinit` at O1 for NVIDIA compiler bug 6861191.
Other compilation settings follow the upstream NVIDIA recipe. The managed
runtime bundle carries the source/configuration and four executables from
build to run; run does not clone or compile source.

`SCALE_LETKF_INPUT_ROOT` defaults to
`/data1/rkp00015/CX_input/SCALE-LETKF`. It must contain the expanded
`scale_database`, the mean/0001/0002 boundary files under
`result/SC23/20210730060000/bdyorg`, and the observation file
`result/SC23/obs_radar/radar_20210730060030.dat`. These inputs are read directly.
This route does not extract the large archives. It fails before starting MPS
when the expanded inputs are missing.

The copied benchmark configuration is small. Only the namelist fields for
external boundary data, radar and database inputs point at the shared input
root. Preprocessing, initialization, history, restart, analysis and read/write
mean fields use the run's own directory. The shared result tree is never
linked as an output destination. Generated configurations and logs are retained
on success or failure.

The FOM keeps Benchkit's existing `SCALE-LETKF` definition: the sum of the
common runner's elapsed seconds for SCALE and LETKF, excluding pp and init.
Internal SCALE/LETKF timers are separate measurements. Successful
process exits and positive timing are required; this is not an independent
numerical-accuracy test. MPS uses the allocated GPU UUID and a private control
pipe; the EXIT handler shuts down that instance only.
