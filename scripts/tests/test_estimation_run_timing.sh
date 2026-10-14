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
cp "${REPO_DIR}/scripts/estimation/prepare_inputs.py" "${TMP_DIR}/scripts/estimation/prepare_inputs.py"
cp "${REPO_DIR}/scripts/estimation/reestimation_conditions.py" "${TMP_DIR}/scripts/estimation/reestimation_conditions.py"

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

# Commit validation precedes input restoration and estimator execution.
pushd "${TMP_DIR}" >/dev/null
git init -q
git add scripts programs
git -c user.name=Test -c user.email=test@example.test commit -qm fixture
commit=$(git rev-parse HEAD)
BK_ESTIMATION_EXPECTED_COMMIT="$commit" bash scripts/estimation/run.sh timingapp >/dev/null
jq -e --arg commit "$commit" '
  .estimation_execution.benchkit_commit == $commit and
  .estimation_execution.requested_commit == $commit
' results/estimate_timingapp_0.json >/dev/null

rm results/estimate_timingapp_0.json
for requested in develop 0000000000000000000000000000000000000000; do
  if BK_ESTIMATION_EXPECTED_COMMIT="$requested" bash scripts/estimation/run.sh timingapp >/dev/null 2>&1; then
    echo "Commit validation accepted an invalid request" >&2
    exit 1
  fi
  [[ ! -f results/estimate_timingapp_0.json ]]
done
printf '\n# changed\n' >> programs/timingapp/estimate.sh
if BK_ESTIMATION_EXPECTED_COMMIT="$commit" bash scripts/estimation/run.sh timingapp >/dev/null 2>&1; then
  echo "Commit validation accepted tracked changes" >&2
  exit 1
fi
[[ ! -f results/estimate_timingapp_0.json ]]
git add programs/timingapp/estimate.sh
if BK_ESTIMATION_EXPECTED_COMMIT="$commit" bash scripts/estimation/run.sh timingapp >/dev/null 2>&1; then
  echo "Commit validation accepted staged changes" >&2
  exit 1
fi
[[ ! -f results/estimate_timingapp_0.json ]]
popd >/dev/null
echo "estimation commit validation test passed"
