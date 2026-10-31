#!/bin/bash
set -e
system="$1"

source scripts/bk_build.sh
bk_build_declared_source programs/LQCD_dw_solver/source.env
cd "$BK_SOURCE_DIR"

# Old source revisions call a CUDA method that does not exist in their header.
# The upstream fix makes this adjustment a no-op; retain support for older refs.
apply_cuda_init_prempi_workaround() {
  local file=src/lib_alt_Accel/init_alt_Accel.cpp
  [ -r src/lib_alt_Accel/ResourceManager/deviceManager_CUDA.h ] || return 1
  if grep -q 'DeviceManager_CUDA::init_prempi' "$file" &&
     ! grep -q init_prempi src/lib_alt_Accel/ResourceManager/deviceManager_CUDA.h; then
    sed -i '/DeviceManager_CUDA::init_prempi/d' "$file" || return $?
  fi
}
bk_source_adjustment cuda-init-prempi \
  'Remove the unavailable CUDA init_prempi call on older source revisions' \
  src/lib_alt_Accel/init_alt_Accel.cpp apply_cuda_init_prempi_workaround

jobs=8
arch=""
case "$system" in
  Fugaku|FugakuCN)
    cp Makefile_target.inc Makefile_target.inc.keep
    if [ "$system" = FugakuCN ]; then
      jobs=12
      sed -i 's/FCCpx/FCC/g' Makefile_target.inc
    fi
    variants=(fugaku_acle)
    ;;
  MiyabiC|AVX512) variants=(simd_avx512) ;;
  MiyabiG) variants=(openacc cuda); arch=hopper ;;
  RIKYU)
    module load nvhpc-hpcx/26.3
    variants=(openacc cuda); arch=blackwell
    ;;
  OpenACC) variants=(openacc) ;;
  CUDA) variants=(cuda) ;;
  *) echo "Unknown system: $system" >&2; exit 1 ;;
esac

compile_variant() {
  if [ "$variant" = cuda ] && [ "${#variants[@]}" -gt 1 ]; then
    rm -rf build || return $?
    make clean || return $?
    (cd benchmark/domainwall && make clean) || return $?
  fi
  make -j "$jobs" lib || return $?
  (cd benchmark/domainwall && make -j "$jobs")
}

for variant in "${variants[@]}"; do
  cp "Makefile_$variant" Makefile
  if [ -n "$arch" ]; then
    sed -i "s/^use_device_arch *= *.*/use_device_arch = $arch/" Makefile
    grep -q "^use_device_arch = $arch\$" Makefile
  fi
  output=bridge.elf
  if [ "${#variants[@]}" -gt 1 ]; then output="bridge_${variant}.elf"; fi
  bk_build_binary "$variant" benchmark/domainwall/bridge.elf "run/$output" \
    --config Makefile --config Makefile_target.inc -- compile_variant
done

# Preserve the upstream relative gauge path used by the run YAML.
bk_publish_runtime run conf_04040408.txt
