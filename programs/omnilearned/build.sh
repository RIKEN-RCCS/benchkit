#!/bin/bash
set -euo pipefail

system="$1"

# Configs and patches ship next to this script.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARTIFACT_DIR="${PWD}/artifacts"

source scripts/bk_functions.sh

mkdir -p "${ARTIFACT_DIR}"
bk_build_declared_source "${APP_DIR}/source.env"
SRC_DIR="$BK_SOURCE_DIR"

# Prints the train-pass wall time the FOM divides by (the stock epoch timer
# also covers validation and the checkpoint save).
cd "${SRC_DIR}"
bk_source_adjustment train-pass-timer \
  'Measure training pass wall time separately from validation and checkpointing' \
  src/omnilearned/train.py git apply "${APP_DIR}/patches/train_pass_timer.patch"
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
    # pytorch-fugaku image (README: "The Fugaku SIF"), launched with that
    # repo's pf-setup/pf-run at the image's commit; OmniLearned's dependencies
    # are aarch64 wheels installed beside it, and OmniLearned runs from this
    # source tree. The SIF is pulled over HTTPS without credentials, pinned by
    # digest, and checked against its SHA-256; BK_OMNILEARNED_SIF selects a
    # pre-staged file instead.
    SIF="${BK_OMNILEARNED_SIF:-${ARTIFACT_DIR}/pytorch-fugaku-d7fb755.sif}"
    if [[ -z "${BK_OMNILEARNED_SIF:-}" ]]; then
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
    PF_REPO="https://github.com/william-dawson/pytorch-fugaku.git"
    PF_COMMIT="d7fb7556870ad34e543239ee739aa3bebccc795e"
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
# Editable installation may generate this version module; Fugaku writes its stub.
cd "$SRC_DIR"
if [ -f src/omnilearned/_version.py ]; then
  bk_publish_source_runtime src/omnilearned/_version.py
else
  bk_publish_source_runtime
fi
