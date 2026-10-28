#!/bin/bash
set -euo pipefail

system="$1"

# The training script and the Fugaku package list ship next to this script.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="${PWD}/artifacts"

source scripts/bk_functions.sh

mkdir -p "${ARTIFACT_DIR}"
# One version set everywhere: torch 2.11.0, DeepSpeed 0.19.8, transformers 4.57.6, accelerate 1.15.0.
TORCH="torch==2.11.0"
STACK=("transformers==4.57.6" "accelerate==1.15.0")

venv_stack() {  # venv_stack <torch index args...>: a venv with the stack in artifacts/venv
  python3 -m venv "${ARTIFACT_DIR}/venv"
  "${ARTIFACT_DIR}/venv/bin/pip" install --upgrade pip
  "${ARTIFACT_DIR}/venv/bin/pip" install numpy "${TORCH}" "$@"
  # DeepSpeed ships as an sdist; no ops are prebuilt (DS_BUILD_OPS=0), the CPU ones JIT-compile.
  DS_BUILD_OPS=0 "${ARTIFACT_DIR}/venv/bin/pip" install --no-build-isolation "deepspeed==0.19.8"
  "${ARTIFACT_DIR}/venv/bin/pip" install "${STACK[@]}"
}

case "$system" in
  RIKYU)
    # aarch64 PyPI torch is the CUDA 13.0 wheel; DeepSpeed's install checks for a CUDA toolkit.
    module load cuda/13.2.2
    export CUDA_HOME="${CUDA_HOME:-$(dirname "$(dirname "$(command -v nvcc)")")}"
    venv_stack
    ;;
  RC_DGXSP)
    export CUDA_HOME=/usr/local/cuda-13.0 PATH="/usr/local/cuda-13.0/bin:${PATH}"
    venv_stack
    ;;
  RC_GENOA)
    # The CPU wheel: PyPI's x86 torch bundles CUDA libraries this node cannot use.
    DS_ACCELERATOR=cpu venv_stack --index-url https://download.pytorch.org/whl/cpu
    ;;
  Fugaku)
    # The login node is x86 and compute is A64FX. The runtime is the pytorch-fugaku image
    # (README: "Fugaku"), launched with that repo's pf-setup/pf-run at the same commit; the
    # Python stack is aarch64 wheels in artifacts/pydeps, installed by a pinned static uv.
    SIF="${BK_DEEPSPEED_LLM_SIF:-/vol0200/share/ra000009/CX_input/deepspeed-llm/pytorch-fugaku-b5879f2.sif}"
    if [[ ! -f "${SIF}" ]]; then
      echo "SIF not found: ${SIF} -- see README.md, \"Fugaku\"" >&2
      exit 1
    fi
    bk_fetch_source "https://github.com/william-dawson/pytorch-fugaku.git" "${ARTIFACT_DIR}/pytorch-fugaku" \
      main "b5879f24d25f6f169403cbdb1c2f0261e9069872"
    UV_VERSION=0.9.5
    curl -sSfL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-musl.tar.gz" \
      | tar xz -C "${ARTIFACT_DIR}"
    UV="${ARTIFACT_DIR}/uv-x86_64-unknown-linux-musl/uv"
    rm -rf "${ARTIFACT_DIR}/pydeps"
    UVARGS=(--target "${ARTIFACT_DIR}/pydeps" --python-platform aarch64-manylinux_2_28 --python-version 3.10 --no-deps)
    UV_CACHE_DIR="${ARTIFACT_DIR}/uv-cache" "${UV}" pip install "${UVARGS[@]}" --no-build \
      -r "${APP_DIR}/fugaku-requirements.txt"
    # DeepSpeed is pure Python: uv builds its wheel (CPU accelerator, no ops) without torch.
    DS_BUILD_OPS=0 UV_CACHE_DIR="${ARTIFACT_DIR}/uv-cache" "${UV}" pip install "${UVARGS[@]}" "deepspeed==0.19.8"
    rm -rf "${ARTIFACT_DIR}/uv-cache"
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

cp "${APP_DIR}/llama_train.py" "${ARTIFACT_DIR}/"
