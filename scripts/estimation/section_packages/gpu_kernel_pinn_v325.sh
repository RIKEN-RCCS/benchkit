#!/bin/bash
# PerfTools PINN v3.25, normalized by prediction on the source GPU.
bk_section_package_metadata_gpu_kernel_pinn_v325() {
  cat "${BASH_SOURCE[0]%/*}/gpu_kernel_pinn_v325.metadata.json"
}
bk_section_package_check_applicability_gpu_kernel_pinn_v325() {
  _bk_gpu_neural_check "$1" "$2" pinn325
}
bk_section_package_transform_gpu_kernel_pinn_v325() {
  _bk_gpu_neural_transform "$1" pinn325
}
