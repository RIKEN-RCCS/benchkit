#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping timing observations test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

source "${REPO_DIR}/scripts/bk_functions.sh"

pushd "${TMP_DIR}" >/dev/null
mkdir -p results

cat > results/detail_CASE0.json <<'JSON'
{
  "schema_version": 1,
  "producer": "demoapp",
  "kind": "demo_timer_table",
  "exp": "CASE0",
  "summary": {
    "timer_count": 3,
    "schema_record_count": 1,
    "has_overlap_probe_schema": false
  },
  "timers": [
    {"id": "solve", "total_seconds": 1.0}
  ]
}
JSON

bk_record_timing_observation \
  --artifact results/detail_CASE0.json \
  --note "not projected to fom_breakdown"

cat > results/detail_CASE1.json <<'JSON'
{
  "schema_version": 2,
  "producer": "profiler-x",
  "kind": "call_tree",
  "exp": "CASE1",
  "summary": {
    "timer_count": 20,
    "schema_record_count": 0
  }
}
JSON

bk_record_timing_observation \
  --id profiler-case1 \
  --artifact results/detail_CASE1.json \
  --kind sampled-profile \
  --format sampled-profile/v1 \
  --summary-json '{"timer_count":20,"sampled":true}'

jq -e '
  .schema_version == 1 and
  (.observations | length) == 2 and
  .observations[0].id == "detail_CASE0" and
  .observations[0].producer == "demoapp" and
  .observations[0].format == "demo_timer_table/v1" and
  .observations[0].result_exp == "CASE0" and
  .observations[0].artifact.path == "results/detail_CASE0.json" and
  .observations[0].summary.timer_count == 3 and
  .observations[0].note == "not projected to fom_breakdown" and
  .observations[1].id == "profiler-case1" and
  .observations[1].kind == "sampled-profile" and
  .observations[1].format == "sampled-profile/v1" and
  .observations[1].producer == "profiler-x" and
  .observations[1].summary.sampled == true
' results/timing_observations.json >/dev/null

if bk_record_timing_observation --artifact ../outside.json >/dev/null 2>&1; then
  echo "bk_record_timing_observation accepted an unsafe artifact path" >&2
  exit 1
fi

bk_reset_timing_observations
test ! -e results/timing_observations.json
test ! -e results/.timing_observation_items.jsonl

popd >/dev/null

echo "timing observations test passed"
