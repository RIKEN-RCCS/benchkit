#!/bin/bash
# gpu_kernel_mlp_v41.sh - Thin package wrapper for PerfTools MLP_NN/v4.1.

bk_section_package_metadata_gpu_kernel_mlp_v41() {
  cat "${BASH_SOURCE[0]%/*}/gpu_kernel_mlp_v41.metadata.json"
}

bk_section_package_check_applicability_gpu_kernel_mlp_v41() (
  export BK_GPU_MLP_PACKAGE_NAME="gpu_kernel_mlp_v41"
  export BK_GPU_MLP_VERSION_DIR="v4.1"
  export BK_GPU_MLP_PREDICT_SCRIPT="predict_v41.py"
  export BK_GPU_MLP_MODEL_VERSION="v4.1"
  export BK_GPU_MLP_SCALING_METHOD="gpu-kernel-mlp-v4.1"
  bk_section_package_check_applicability_gpu_kernel_mlp_v15 "$@"
)

bk_section_package_transform_gpu_kernel_mlp_v41() (
  export BK_GPU_MLP_PACKAGE_NAME="gpu_kernel_mlp_v41"
  export BK_GPU_MLP_VERSION_DIR="v4.1"
  export BK_GPU_MLP_PREDICT_SCRIPT="predict_v41.py"
  export BK_GPU_MLP_MODEL_VERSION="v4.1"
  export BK_GPU_MLP_SCALING_METHOD="gpu-kernel-mlp-v4.1"
  bk_section_package_transform_gpu_kernel_mlp_v15 "$@"
)
