#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping estimation run timing test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/programs/timingapp" "${TMP_DIR}/scripts/estimation" "${TMP_DIR}/results"
cp "${REPO_DIR}/scripts/estimation/run.sh" "${TMP_DIR}/scripts/estimation/run.sh"

cat > "${TMP_DIR}/programs/timingapp/estimate.sh" <<'EOF'
#!/bin/bash
set -euo pipefail

input_json="$1"
mkdir -p results
jq -n \
  --arg source_system "$(jq -r '.system' "$input_json")" \
  '{
    code: "timingapp",
    exp: "CASE0",
    estimate_metadata: {
      source_result: {
        system: $source_system
      }
    }
  }' > results/estimate_timingapp_0.json
EOF
chmod +x "${TMP_DIR}/programs/timingapp/estimate.sh"

cat > "${TMP_DIR}/results/result0.json" <<'JSON'
{
  "code": "timingapp",
  "system": "TestSystem",
  "Exp": "CASE0",
  "FOM": 1.0
}
JSON

pushd "${TMP_DIR}" >/dev/null
bash scripts/estimation/run.sh timingapp >/dev/null
popd >/dev/null

jq -e '
  .estimation_timing.schema_version == 1 and
  .estimation_timing.elapsed_time >= 0 and
  .estimation_timing.unit == "s" and
  .estimation_timing.recorded_by == "scripts/estimation/run.sh"
' "${TMP_DIR}/results/estimate_timingapp_0.json" >/dev/null

echo "estimation run timing test passed"
