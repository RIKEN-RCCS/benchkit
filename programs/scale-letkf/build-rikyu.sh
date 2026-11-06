#!/bin/bash
set -euo pipefail
APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$APP_DIR/runtime-rikyu.sh"
scale_rikyu_environment
source scripts/bk_functions.sh
jobs="${SCALE_LETKF_BUILD_JOBS:-4}"
[[ "$jobs" =~ ^[1-9][0-9]?$ ]] || exit 2
bk_build_source https://github.com/SCALE-LETKF-RIKEN/scale-letkf-FugakuNEXT \
    "${SCALE_LETKF_BRANCH:-master}" "${SCALE_LETKF_SOURCE_COMMIT:-}"
cd "$BK_SOURCE_DIR"
bk_source_adjustment nvhpc-mkinit-o1 'Compile mod_mkinit at O1 for NVIDIA HPC SDK bug 6861191' \
    scale/scale-rm/src/Makefile python3 "$APP_DIR/prepare-rikyu.py" workaround "$BK_SOURCE_DIR"
acc_flags='-acc -cuda -Minfo=accel -cudalib=cusparse,nvtx -DUSE_CUDALIB -gpu=cc100'
make -C scale/scale-rm/src -j "$jobs" "FFLAGS_OPENACC=$acc_flags"
make -C scale/scale-letkf/scale -j "$jobs" "FFLAGS_OPENACC=$acc_flags"
bk_publish_source_runtime \
    scale/scale-letkf/scale/ensmodel/scale-rm_pp_ens \
    scale/scale-letkf/scale/ensmodel/scale-rm_init_ens \
    scale/scale-letkf/scale/ensmodel/scale-rm_ens \
    scale/scale-letkf/scale/letkf/letkf
