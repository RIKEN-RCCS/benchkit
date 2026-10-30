#!/bin/bash
set -euo pipefail

system="$1"

# Configs and patches ship next to this script.
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
  Fugaku)
    # The login node is x86 and compute is A64FX. The runtime is the
    # pytorch-fugaku image, pre-staged (README: "The Fugaku SIF") and launched
    # with that repo's pf-setup/pf-run; OmniLearned's dependencies are aarch64
    # wheels installed beside it, and OmniLearned runs from this source tree.
    SIF="${BK_OMNILEARNED_SIF:-/vol0200/share/ra000009/CX_input/omnilearned/pytorch-fugaku-ed93ef4.sif}"
    if [[ ! -f "${SIF}" ]]; then
      echo "SIF not found: ${SIF} -- see README.md, \"The Fugaku SIF\"" >&2
      exit 1
    fi
    PF_REPO="https://github.com/william-dawson/pytorch-fugaku.git"
    PF_COMMIT="c66cdc79d6053c5a48f75000d1fa849c67099056"
    rm -rf "${ARTIFACT_DIR}/pytorch-fugaku"
    git clone -q "${PF_REPO}" "${ARTIFACT_DIR}/pytorch-fugaku"
    git -C "${ARTIFACT_DIR}/pytorch-fugaku" checkout -q "${PF_COMMIT}"
    # A static uv cross-installs wheels using an existing compatible interpreter.
    UV_VERSION=0.13.4
    # GitHub release asset digest; update together with UV_VERSION.
    UV_SHA256=28d4385f9f9d1d1c7654d85b3855e0e2615b2f6cc13136a2edff858bbdc16ff1
    UV_ARCHIVE=$(mktemp "${ARTIFACT_DIR}/uv-${UV_VERSION}.XXXXXX.tar.gz")
    curl -sSfL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-musl.tar.gz" \
      --output "${UV_ARCHIVE}"
    bk_verify_file_sha256 "${UV_ARCHIVE}" "${UV_SHA256}" "uv ${UV_VERSION}" > /dev/null
    tar xzf "${UV_ARCHIVE}" -C "${ARTIFACT_DIR}"
    rm -- "${UV_ARCHIVE}"
    rm -rf "${ARTIFACT_DIR}/pydeps"
    UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR="${ARTIFACT_DIR}/uv-cache" "${ARTIFACT_DIR}/uv-x86_64-unknown-linux-musl/uv" pip install \
      --no-python-downloads \
      --target "${ARTIFACT_DIR}/pydeps" --python-platform aarch64-manylinux_2_28 --python-version 3.10 \
      --no-deps --no-build -r "${APP_DIR}/fugaku-requirements.txt"
    # Not pip-installed, so stub the version file hatch-vcs would generate.
    if ! grep -q 'version = ' "${SRC_DIR}/src/omnilearned/_version.py" 2>/dev/null; then
      echo 'version = "0.0.0-benchkit"' > "${SRC_DIR}/src/omnilearned/_version.py"
    fi
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

cp "${APP_DIR}"/top_medium_pretrain*.yaml "${ARTIFACT_DIR}/"
