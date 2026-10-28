#!/bin/bash
set -euo pipefail

system="$1"

# The benchmark configs ship next to this script.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPO="https://github.com/ViniciusMikuni/OmniLearned.git"
# main @ merge of PR #21 ("omnilearnedv2"). Upstream needs torch>=2.11,<2.14;
# 2.11.0 is the version measured here.
REF="main"
EXPECTED_COMMIT="29948e7930c45e83eb10b5779e3f7ff83cdae743"
SRC_DIR="${PWD}/OmniLearned"
ARTIFACT_DIR="${PWD}/artifacts"

source scripts/bk_functions.sh

mkdir -p "${ARTIFACT_DIR}"
bk_fetch_source "${REPO}" "OmniLearned" "${REF}" "${EXPECTED_COMMIT}"

# Prints the train-pass wall time the FOM divides by (the stock epoch timer
# also covers validation and the checkpoint save).
cd "${SRC_DIR}"
if ! grep -q "Train pass wall" src/omnilearned/train.py; then
  git apply "${APP_DIR}/patches/train_pass_timer.patch"
fi
cd - > /dev/null

case "$system" in
  RIKYU|RC_GH200|RC_DGXSP|RC_GENOA)
    # On aarch64, PyPI torch is the CUDA wheel; one recipe serves all four.
    python3 -m venv "${ARTIFACT_DIR}/venv"
    "${ARTIFACT_DIR}/venv/bin/pip" install --upgrade pip
    "${ARTIFACT_DIR}/venv/bin/pip" install "torch==2.11.0"
    "${ARTIFACT_DIR}/venv/bin/pip" install -e "${SRC_DIR}"
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

cp "${APP_DIR}"/top_medium_pretrain*.yaml "${ARTIFACT_DIR}/"
