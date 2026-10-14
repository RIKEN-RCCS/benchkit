#!/bin/bash
# gpu_kernel_mlp_v21.sh - Thin package wrapper for PerfTools MLP_NN/v2.1.

bk_section_package_metadata_gpu_kernel_mlp_v21() {
  cat "${BASH_SOURCE[0]%/*}/gpu_kernel_mlp_v21.metadata.json"
}

bk_section_package_check_applicability_gpu_kernel_mlp_v21() (
  export BK_GPU_MLP_PACKAGE_NAME="gpu_kernel_mlp_v21"
  export BK_GPU_MLP_VERSION_DIR="v2.1"
  export BK_GPU_MLP_PREDICT_SCRIPT="predict_v21.py"
  export BK_GPU_MLP_MODEL_VERSION="v2.1"
  export BK_GPU_MLP_SCALING_METHOD="gpu-kernel-mlp-v2.1"
  bk_section_package_check_applicability_gpu_kernel_mlp_v15 "$@"
)

bk_section_package_transform_gpu_kernel_mlp_v21() (
  export BK_GPU_MLP_PACKAGE_NAME="gpu_kernel_mlp_v21"
  export BK_GPU_MLP_VERSION_DIR="v2.1"
  export BK_GPU_MLP_PREDICT_SCRIPT="predict_v21.py"
  export BK_GPU_MLP_MODEL_VERSION="v2.1"
  export BK_GPU_MLP_SCALING_METHOD="gpu-kernel-mlp-v2.1"
  bk_section_package_transform_gpu_kernel_mlp_v15 "$@"
)
