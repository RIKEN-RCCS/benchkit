#!/bin/bash
# gpu_kernel_mlp_v40.sh - Thin package wrapper for PerfTools MLP_NN/v4.0.

bk_section_package_metadata_gpu_kernel_mlp_v40() {
  cat <<'EOF'
{
  "name": "gpu_kernel_mlp_v40",
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
    "PerfTools MLP_NN/v4.0 prepared input CSV",
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

bk_section_package_check_applicability_gpu_kernel_mlp_v40() (
  export BK_GPU_MLP_PACKAGE_NAME="gpu_kernel_mlp_v40"
  export BK_GPU_MLP_VERSION_DIR="v4.0"
  export BK_GPU_MLP_PREDICT_SCRIPT="predict_v40.py"
  export BK_GPU_MLP_MODEL_VERSION="v4.0"
  export BK_GPU_MLP_SCALING_METHOD="gpu-kernel-mlp-v4.0"
  bk_section_package_check_applicability_gpu_kernel_mlp_v15 "$@"
)

bk_section_package_transform_gpu_kernel_mlp_v40() (
  export BK_GPU_MLP_PACKAGE_NAME="gpu_kernel_mlp_v40"
  export BK_GPU_MLP_VERSION_DIR="v4.0"
  export BK_GPU_MLP_PREDICT_SCRIPT="predict_v40.py"
  export BK_GPU_MLP_MODEL_VERSION="v4.0"
  export BK_GPU_MLP_SCALING_METHOD="gpu-kernel-mlp-v4.0"
  bk_section_package_transform_gpu_kernel_mlp_v15 "$@"
)
