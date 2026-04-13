#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/results" "${TMP_DIR}/bk_profiler_artifact"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping result profile_data test"
  exit 0
fi

cat > "${TMP_DIR}/results/result" <<'EOF'
FOM:1.234 FOM_version:test Exp:CASE0 node_count:1 numproc_node:1 nthreads:2
EOF

cat > "${TMP_DIR}/bk_profiler_artifact/meta.json" <<'EOF'
{
  "tool": "fapp",
  "level": "single",
  "report_format": "text",
  "raw_dir": "raw",
  "runs": [
    {
      "name": "rep1",
      "event": "pa1",
      "raw_path": "raw/rep1",
      "reports": [
        {"kind": "summary_text", "path": "reports/fapp_A_rep1.txt"}
      ]
    }
  ]
}
EOF

tar -czf "${TMP_DIR}/results/padata0.tgz" -C "${TMP_DIR}" bk_profiler_artifact

pushd "${TMP_DIR}" >/dev/null
bash "${REPO_DIR}/scripts/result.sh" qws Fugaku cross build run 999 >/dev/null
popd >/dev/null

RESULT_JSON="${TMP_DIR}/results/result0.json"
test -f "${RESULT_JSON}"
grep -q '"profile_data"' "${RESULT_JSON}"
grep -q '"tool": "fapp"' "${RESULT_JSON}"
grep -q '"level": "single"' "${RESULT_JSON}"
grep -q '"report_format": "text"' "${RESULT_JSON}"
grep -q '"run_count": 1' "${RESULT_JSON}"
grep -q '"pa1"' "${RESULT_JSON}"
grep -q '"summary_text"' "${RESULT_JSON}"

echo "result profile_data test passed"
