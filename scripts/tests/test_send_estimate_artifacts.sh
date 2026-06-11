#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/bin" "${TMP_DIR}/results/estimation_artifacts/gpu_kernel_mlp_v15"
mkdir -p "${TMP_DIR}/results/estimation_artifacts/gpu_kernel_mlp_v15/genesis_prepare/padata/raw/rep1"

cat > "${TMP_DIR}/results/estimate0.json" <<'JSON'
{
  "code": "genesis",
  "exp": "p8",
  "current_system": {
    "benchmark": {
      "uuid": "11111111-2222-3333-4444-555555555555"
    }
  },
  "estimate_metadata": {
    "source_result_uuid": "11111111-2222-3333-4444-555555555555"
  }
}
JSON

cat > "${TMP_DIR}/results/estimation_artifacts/gpu_kernel_mlp_v15/input.csv" <<'EOF'
kernel_name,Execution Time [ns]
dummy,1
EOF
cat > "${TMP_DIR}/results/estimation_artifacts/gpu_kernel_mlp_v15/pred.csv" <<'EOF'
kernel_name,Execution Time [ns]
dummy,2
EOF
echo "predictor log" > "${TMP_DIR}/results/estimation_artifacts/gpu_kernel_mlp_v15/gpu_kernel_region.log"
echo "raw report" > "${TMP_DIR}/results/estimation_artifacts/gpu_kernel_mlp_v15/genesis_prepare/padata/raw/rep1/profile.ncu-rep"
echo "raw csv" > "${TMP_DIR}/results/estimation_artifacts/gpu_kernel_mlp_v15/genesis_prepare/padata/raw/rep1/profile_raw.csv"
echo "padata duplicate" > "${TMP_DIR}/results/estimation_artifacts/gpu_kernel_mlp_v15/padata0.tgz"

cat > "${TMP_DIR}/bin/curl" <<'EOF'
#!/bin/bash
set -euo pipefail

printf '%s\n' "$*" >> "${CURL_LOG:?CURL_LOG is required}"

archive=""
for arg in "$@"; do
  case "$arg" in
    file=@*) archive="${arg#file=@}" ;;
  esac
done

if printf '%s\n' "$*" | grep -q '/api/ingest/estimation-artifacts'; then
  if [ "${FAKE_ESTIMATION_ARTIFACTS_NEW_STATUS:-200}" = "404" ]; then
    echo "curl: (22) The requested URL returned error: 404" >&2
    exit 22
  fi
fi

if printf '%s\n' "$*" | grep -Eq '/api/ingest/estimation-(artifacts|inputs)'; then
  if [ "${FAKE_ESTIMATION_ARTIFACTS_STATUS:-200}" = "413" ]; then
    echo "curl: (22) The requested URL returned error: 413" >&2
    exit 22
  fi
  test -n "$archive"
  tar -tzf "$archive" > "${ESTIMATION_ARTIFACTS_TAR_LIST:?ESTIMATION_ARTIFACTS_TAR_LIST is required}"
fi

printf '%s\n' '{"status":"ok"}'
EOF
chmod +x "${TMP_DIR}/bin/curl"

export PATH="${TMP_DIR}/bin:${PATH}"
export CURL_LOG="${TMP_DIR}/curl.log"
export ESTIMATION_ARTIFACTS_TAR_LIST="${TMP_DIR}/estimation_artifacts_tar_list.txt"
export RESULT_SERVER="https://result.example.test"
export RESULT_SERVER_KEY="dummy-key"

cd "$TMP_DIR"
bash "${REPO_DIR}/scripts/result_server/send_estimate.sh"

grep -q '/api/ingest/estimate' "$CURL_LOG"
grep -q '/api/ingest/estimation-artifacts' "$CURL_LOG"
grep -q 'id=11111111-2222-3333-4444-555555555555' "$CURL_LOG"
grep -q './gpu_kernel_mlp_v15/input.csv' "$ESTIMATION_ARTIFACTS_TAR_LIST"
grep -q './gpu_kernel_mlp_v15/pred.csv' "$ESTIMATION_ARTIFACTS_TAR_LIST"
grep -q './gpu_kernel_mlp_v15/gpu_kernel_region.log' "$ESTIMATION_ARTIFACTS_TAR_LIST"
! grep -q 'profile.ncu-rep' "$ESTIMATION_ARTIFACTS_TAR_LIST"
! grep -q 'profile_raw.csv' "$ESTIMATION_ARTIFACTS_TAR_LIST"
! grep -q 'padata0.tgz' "$ESTIMATION_ARTIFACTS_TAR_LIST"

rm -f "$CURL_LOG" "$ESTIMATION_ARTIFACTS_TAR_LIST"
FAKE_ESTIMATION_ARTIFACTS_STATUS=413 bash "${REPO_DIR}/scripts/result_server/send_estimate.sh"
grep -q '/api/ingest/estimate' "$CURL_LOG"
grep -q '/api/ingest/estimation-artifacts' "$CURL_LOG"
test ! -e results/estimation_artifacts_11111111-2222-3333-4444-555555555555.tgz

rm -f "$CURL_LOG" "$ESTIMATION_ARTIFACTS_TAR_LIST"
FAKE_ESTIMATION_ARTIFACTS_NEW_STATUS=404 bash "${REPO_DIR}/scripts/result_server/send_estimate.sh"
grep -q '/api/ingest/estimation-artifacts' "$CURL_LOG"
grep -q '/api/ingest/estimation-inputs' "$CURL_LOG"
grep -q './gpu_kernel_mlp_v15/input.csv' "$ESTIMATION_ARTIFACTS_TAR_LIST"
