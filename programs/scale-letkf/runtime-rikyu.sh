#!/bin/bash
# Shared application toolchain for the build and compute hosts.
scale_rikyu_environment() {
    module load "${SCALE_LETKF_MODULE:-nvhpc-hpcx/26.3}"
    local nc="${SCALE_LETKF_NC_CONFIG:-nc-config}"
    local nf="${SCALE_LETKF_NF_CONFIG:-nf-config}"
    command -v "$nc" >/dev/null && command -v "$nf" >/dev/null || {
        echo 'Set SCALE_LETKF_NC_CONFIG and SCALE_LETKF_NF_CONFIG to compatible NetCDF installations' >&2
        return 1
    }
    export SCALE_SYS=Linux64-nvidia SCALE_ENABLE_OPENMP=F SCALE_ENABLE_OPENACC=T
    export SCALE_ENABLE_MATHLIB=T
    SCALE_NETCDF_INCLUDE="$("$nc" --cflags) $("$nf" --fflags)"
    SCALE_NETCDF_LIBS="$("$nf" --flibs) $("$nc" --libs)"
    SCALE_MATHLIB_LIBS="${SCALE_LETKF_MATHLIB_LIBS:--L$(dirname "$(command -v nvfortran)")/../lib -llapack -lblas}"
    export SCALE_NETCDF_INCLUDE SCALE_NETCDF_LIBS SCALE_MATHLIB_LIBS
    LD_LIBRARY_PATH="$("$nf" --prefix)/lib:$("$nc" --prefix)/lib:${LD_LIBRARY_PATH:-}"
    export LD_LIBRARY_PATH
}
