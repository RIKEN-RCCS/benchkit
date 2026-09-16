#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/project"
ln -s "${REPO_DIR}/config" "${TMP_DIR}/project/config"
ln -s "${REPO_DIR}/programs" "${TMP_DIR}/project/programs"
ln -s "${REPO_DIR}/scripts" "${TMP_DIR}/project/scripts"

pushd "${TMP_DIR}/project" >/dev/null

bash scripts/matrix_generate.sh code=sbd system=RIKYU nodes=1
grep -q '^sbd_RIKYU_N1_P4_T32_run:' .gitlab-ci.generated.yml
if grep -q '^sbd_RIKYU_N2_P4_T32_run:' .gitlab-ci.generated.yml; then
  echo "nodes=1 filter must not emit the SBD RIKYU 2-node job" >&2
  exit 1
fi
if grep -q '^sbd_RIKYU_N4_P4_T32_run:' .gitlab-ci.generated.yml; then
  echo "nodes=1 filter must not emit the SBD RIKYU 4-node job" >&2
  exit 1
fi

bash scripts/matrix_generate.sh code=sbd system=RIKYU nodes='2, 4'
if grep -q '^sbd_RIKYU_N1_P4_T32_run:' .gitlab-ci.generated.yml; then
  echo "nodes=2,4 filter must not emit the SBD RIKYU 1-node job" >&2
  exit 1
fi
grep -q '^sbd_RIKYU_N2_P4_T32_run:' .gitlab-ci.generated.yml
grep -q '^sbd_RIKYU_N4_P4_T32_run:' .gitlab-ci.generated.yml

popd >/dev/null

echo "matrix generation filter test passed"
