#!/bin/bash
# PerfTools MLP-NN v4.55, normalized by prediction on the source GPU.
bk_section_package_metadata_gpu_kernel_mlp_v455() {
  cat "${BASH_SOURCE[0]%/*}/gpu_kernel_mlp_v455.metadata.json"
}
bk_section_package_check_applicability_gpu_kernel_mlp_v455() {
  _bk_gpu_neural_check "$1" "$2" mlp455
}
bk_section_package_transform_gpu_kernel_mlp_v455() {
  _bk_gpu_neural_transform "$1" mlp455
}
