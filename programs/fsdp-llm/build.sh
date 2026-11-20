#!/bin/bash
set -euo pipefail

system="$1"

# The training script ships next to this script.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="${PWD}/artifacts"

source scripts/bk_functions.sh

mkdir -p "${ARTIFACT_DIR}"

# torch 2.11.0 and transformers 4.57.6, as in the Fugaku image.
venv_stack() {  # venv_stack <torch index args...>: a venv with the stack in artifacts/venv
  python3 -m venv "${ARTIFACT_DIR}/venv"
  "${ARTIFACT_DIR}/venv/bin/pip" install --upgrade pip
  "${ARTIFACT_DIR}/venv/bin/pip" install numpy "torch==2.11.0" "$@"
  "${ARTIFACT_DIR}/venv/bin/pip" install "transformers==4.57.6"
}

case "$system" in
  RIKYU)
    # On aarch64 PyPI's torch is the CUDA 13.0 wheel.
    module load cuda/13.2.2
    venv_stack
    ;;
  RC_DGXSP)
    venv_stack
    ;;
  RC_GENOA)
    # The CPU wheel: PyPI's x86 torch bundles CUDA libraries this node cannot use.
    venv_stack --index-url https://download.pytorch.org/whl/cpu
    ;;
  Fugaku)
    # The login node is x86 and compute is A64FX. The runtime is the pytorch-fugaku image
    # (README: "The Fugaku SIF"), which carries torch and transformers; it is launched with that
    # repo's pf-setup/pf-run at the image's commit. The SIF is pulled over HTTPS without
    # credentials, pinned by digest, and checked against its SHA-256; BK_FSDP_LLM_SIF selects a
    # pre-staged file instead.
    SIF="${BK_FSDP_LLM_SIF:-${ARTIFACT_DIR}/pytorch-fugaku-d7fb755.sif}"
    if [[ -z "${BK_FSDP_LLM_SIF:-}" ]]; then
      # The SIF that pytorch-fugaku's CI published for this commit, fetched as a registry blob:
      # its address is the file's SHA-256 (README: "The Fugaku SIF").
      SIF_SHA256=267d5a25ca5bbbfe10860c09529697e54af57c6012b53c2c7701fdfb1f96fd08
      if [[ ! -f "${SIF}" ]]; then
        REG=https://ghcr.io/v2/william-dawson/pytorch-fugaku
        TOKEN=$(curl -sSf "https://ghcr.io/token?scope=repository:william-dawson/pytorch-fugaku:pull" |
          sed 's/.*"token":"\([^"]*\)".*/\1/')
        curl -sSfL -H "Authorization: Bearer ${TOKEN}" -o "${SIF}.part" "${REG}/blobs/sha256:${SIF_SHA256}"
        mv -- "${SIF}.part" "${SIF}"
      fi
      bk_verify_file_sha256 "${SIF}" "${SIF_SHA256}" "pytorch-fugaku SIF" > /dev/null
    elif [[ ! -f "${SIF}" ]]; then
      echo "SIF not found: ${SIF} -- see README.md, \"The Fugaku SIF\"" >&2
      exit 1
    fi
    bk_fetch_source "https://github.com/william-dawson/pytorch-fugaku.git" "${ARTIFACT_DIR}/pytorch-fugaku" \
      main "d7fb7556870ad34e543239ee739aa3bebccc795e"
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

cp "${APP_DIR}/llm_train.py" "${ARTIFACT_DIR}/"
