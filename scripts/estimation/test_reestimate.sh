#!/bin/bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <code> <estimate_result_uuid>"
  echo "  <code>: program name (directory under programs/)"
  echo "  <estimate_result_uuid>: UUID to use as the re-estimation entry point"
  echo ""
  echo "Examples:"
  echo "  $0 qws 11111111-2222-3333-4444-555555555555"
  exit 1
fi

code="$1"
input_uuid="$2"

if [[ ! "$input_uuid" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "ERROR: UUID format looks invalid: $input_uuid" >&2
  exit 1
fi

if [[ ! -d "programs/$code" ]]; then
  echo "ERROR: programs/$code does not exist" >&2
  exit 1
fi

if [[ -z "${RESULT_SERVER:-}" || -z "${RESULT_SERVER_KEY:-}" ]]; then
  echo "ERROR: RESULT_SERVER and RESULT_SERVER_KEY must be set" >&2
  exit 1
fi

rm -f results/result*.json results/estimate*.json results/source_estimate.json
mkdir -p results

export estimate_result_uuid="$input_uuid"

export code

echo "Re-estimation test"
echo "  code: $code"
echo "  uuid: $input_uuid"
echo ""

echo "[1/2] Fetching source result"
bash scripts/result_server/fetch_result_by_uuid.sh

echo ""
echo "[2/2] Running estimation"
bash scripts/estimation/run.sh "$code"

echo ""
echo "Generated files:"
ls results/result*.json results/estimate*.json 2>/dev/null || true

if [[ -f results/result0.json ]]; then
  echo ""
  echo "Fetched result metadata:"
  jq '{code, system, Exp, _server_uuid, _server_timestamp}' results/result0.json || true
fi

if compgen -G "results/estimate*.json" > /dev/null; then
  for estimate_file in results/estimate*.json; do
    echo ""
    echo "Estimate metadata for $estimate_file:"
    jq '{
      code,
      exp,
      performance_ratio,
      applicability,
      reestimation,
      estimate_metadata: {
        source_result_uuid,
        estimation_result_uuid,
        requested_estimation_package,
        estimation_package
      }
    }' "$estimate_file" || true
  done
else
  echo "WARNING: No estimate*.json files generated"
fi
