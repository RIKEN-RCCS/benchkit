#!/bin/bash
# gpu_kernel_mlp_v21.sh - Thin package wrapper for PerfTools MLP_NN/v2.1.

bk_section_package_metadata_gpu_kernel_mlp_v21() {
  cat <<'EOF'
{
  "name": "gpu_kernel_mlp_v21",
  "fallback_target": "identity",
  "source_system_scope": {
    "kind": "benchmark_system",
    "accepted_values": ["any"]
  },
  "target_system_scope": {
    "accepted_values": ["any"]
  },
  "item_kind_scope": ["section"],
  "required_result_fields": ["name", "app-side GPU section time as time or bench_time"],
  "required_artifact_kinds": [
    "PerfTools MLP_NN/v2.1 prepared input CSV",
    "precomputed prediction CSV",
    "or BenchKit padata archive with Nsight Compute raw CSV"
  ],
  "acquisition_mode": "external",
  "output_fields": [
    "time",
    "bench_time",
    "scaling_method",
    "metrics",
    "package_applicability"
  ]
}
EOF
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
