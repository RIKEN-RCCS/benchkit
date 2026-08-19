#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT
export TMP_DIR

mkdir -p "${TMP_DIR}/results" "${TMP_DIR}/bk_profiler_artifact" "${TMP_DIR}/bin"

cat > "${TMP_DIR}/results/result0.json" <<'EOF'
{
  "code": "qws",
  "system": "Fugaku",
  "FOM": "1.234",
  "FOM_version": "test",
  "Exp": "CASE0",
  "node_count": "1",
  "numproc_node": "1",
  "nthreads": "2",
  "description": "null",
  "confidential": "null",
  "source_info": null,
  "fom_breakdown": {
    "sections": [
      {
        "name": "pme_real_inter",
        "time": 1.0,
        "artifacts": [
          {
            "type": "file_reference",
            "path": "results/padata_k001.tgz"
          }
        ]
      },
      {
        "name": "pme_real_intra",
        "time": 1.0,
        "artifacts": [
          {
            "type": "file_reference",
            "path": "results/padata_k002.tgz"
          }
        ]
      },
      {
        "name": "pairlist",
        "time": 1.0,
        "artifacts": [
          {
            "type": "file_reference",
            "path": "results/padata_k003.tgz"
          }
        ]
      }
    ],
    "overlaps": []
  }
}
EOF

cat > "${TMP_DIR}/bk_profiler_artifact/meta.json" <<'EOF'
{
  "tool": "ncu",
  "level": "single",
  "report_format": "text",
  "raw_dir": "raw",
  "measurement": {
    "ncu_options": ["--target-processes", "all", "--set", "basic", "--launch-count", "1"]
  },
  "runs": [
    {
      "name": "rep1",
      "event": "single",
      "raw_path": "raw/rep1",
      "reports": [
        {"kind": "ncu_report", "path": "raw/rep1/profile.ncu-rep"},
        {"kind": "summary_text", "path": "reports/ncu_import_rep1.txt"}
      ]
    }
  ]
}
EOF

tar -czf "${TMP_DIR}/results/padata0.tgz" -C "${TMP_DIR}" bk_profiler_artifact
tar -czf "${TMP_DIR}/results/padata_k001.tgz" -C "${TMP_DIR}" bk_profiler_artifact
tar -czf "${TMP_DIR}/results/padata_k002.tgz" -C "${TMP_DIR}" bk_profiler_artifact
tar -czf "${TMP_DIR}/results/padata_k003.tgz" -C "${TMP_DIR}" bk_profiler_artifact

cat > "${TMP_DIR}/bin/curl" <<'EOF'
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" >> "${TMP_DIR}/curl_calls.log"
if printf '%s\n' "$*" | grep -q '/api/ingest/result'; then
  printf '%s\n' '{"id":"11111111-2222-3333-4444-555555555555","timestamp":"20260413_230000"}'
  exit 0
fi
if printf '%s\n' "$*" | grep -q '/api/ingest/padata'; then
  printf '%s\n' "$*" >> "${TMP_DIR}/padata_uploads.log"
  if [ "${FAKE_PADATA_STATUS:-200}" = "413" ]; then
    echo "curl: (22) The requested URL returned error: 413" >&2
    exit 22
  fi
  printf '%s\n' '{"status":"uploaded"}'
  exit 0
fi
printf '%s\n' '{"status":"ok"}'
EOF

cat > "${TMP_DIR}/bin/python" <<'EOF'
#!/bin/bash
set -euo pipefail
echo "fake python: unsupported invocation: $*" >&2
exit 1
EOF

cat > "${TMP_DIR}/bin/python3" <<'EOF'
#!/bin/bash
set -euo pipefail
exec "${TMP_DIR}/bin/python" "$@"
EOF

PYTHON_FOR_FAKE_JQ="${PYTHON_FOR_FAKE_JQ:-}"
if [ -z "$PYTHON_FOR_FAKE_JQ" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_FOR_FAKE_JQ="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_FOR_FAKE_JQ="$(command -v python)"
  else
    echo "python3/python not found; skipping send_results profile_data test"
    exit 0
  fi
fi
export PYTHON_FOR_FAKE_JQ

cat > "${TMP_DIR}/bin/jq" <<'EOF'
#!/bin/bash
set -euo pipefail
python_exe="${PYTHON_FOR_FAKE_JQ:?PYTHON_FOR_FAKE_JQ is required}"

if [ "$1" = "-c" ]; then
  shift
  expr="$1"
  input_json="$(cat)"
  INPUT_JSON="$input_json" "$python_exe" - "$expr" <<'PY'
import json
import os
import sys

expr = sys.argv[1]
data = json.loads(os.environ["INPUT_JSON"])
if "tool: .tool" in expr and "report_kinds" in expr:
    summary = {
        "tool": data.get("tool"),
        "level": data.get("level"),
        "report_format": data.get("report_format"),
        "raw_dir": data.get("raw_dir"),
        "run_count": len(data.get("runs", [])),
        "events": [run.get("event") for run in data.get("runs", []) if data.get("tool") == "fapp" and run.get("event")],
        "ncu_options": data.get("measurement", {}).get("ncu_options", []) if data.get("tool") == "ncu" else [],
        "report_kinds": sorted({rep.get("kind") for run in data.get("runs", []) for rep in run.get("reports", []) if rep.get("kind")}),
    }
    print(json.dumps(summary))
    sys.exit(0)
raise SystemExit(1)
PY
fi

if [ "$1" = "-s" ] && [ "$2" = "-c" ]; then
  summaries_file="$4"
  "$python_exe" - "$summaries_file" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    items = [json.loads(line) for line in fh if line.strip()]

def uniq(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result

tools = uniq([item.get("tool") for item in items if item.get("tool")])
levels = uniq([item.get("level") for item in items if item.get("level")])
formats = uniq([item.get("report_format") for item in items if item.get("report_format")])
summary = {
    "tool": tools[0] if len(tools) == 1 else "multiple",
    "level": levels[0] if len(levels) == 1 else "multiple",
    "report_format": formats[0] if len(formats) == 1 else "multiple",
    "raw_dir": "multiple",
    "run_count": sum(item.get("run_count", 0) for item in items),
    "events": uniq([event for item in items for event in item.get("events", [])]),
    "ncu_options": uniq([option for item in items for option in item.get("ncu_options", [])]),
    "report_kinds": uniq([kind for item in items for kind in item.get("report_kinds", [])]),
    "archive_count": len(items),
}
print(json.dumps(summary))
PY
  exit 0
fi

if [ "$1" = "-r" ]; then
  shift
  expr="$1"
  target_file="$2"
  "$python_exe" - "$target_file" "$expr" <<'PY'
import json
import sys

path, expr = sys.argv[1:3]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
if "fom_breakdown.sections" in expr:
    for section in data.get("fom_breakdown", {}).get("sections", []):
        for artifact in section.get("artifacts", []):
            artifact_path = artifact.get("path")
            if artifact_path and artifact_path.split("/")[-1].startswith("padata") and artifact_path.endswith(".tgz"):
                print(artifact_path)
    sys.exit(0)
raise SystemExit(1)
PY
  exit 0
fi

args=("$@")
last_index=$((${#args[@]} - 1))
target_file="${args[$last_index]}"
expr="${args[$((last_index - 1))]}"

if [ "$expr" = "." ]; then
  "$python_exe" - "$target_file" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    json.load(fh)
print("ok")
PY
  exit 0
fi

if [ "${args[0]}" = "--argjson" ] && [ "${args[1]}" = "profile_data" ]; then
  profile_data_json="${args[2]}"
  "$python_exe" - "$target_file" "$profile_data_json" <<'PY'
import json
import sys
path, profile_json = sys.argv[1:3]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
data["profile_data"] = json.loads(profile_json)
print(json.dumps(data, ensure_ascii=False, indent=2))
PY
  exit 0
fi

if [ "${args[0]}" = "--arg" ] && [ "${args[1]}" = "uuid" ] && [ "${args[3]}" = "--arg" ] && [ "${args[4]}" = "timestamp" ]; then
  uuid="${args[2]}"
  timestamp="${args[5]}"
  "$python_exe" - "$target_file" "$uuid" "$timestamp" "$expr" <<'PY'
import json
import sys
path, uuid, timestamp, expr = sys.argv[1:5]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
if "_server_uuid" in expr:
    data["_server_uuid"] = uuid
    data["_server_timestamp"] = timestamp
else:
    file_key = None
    # meta manifest path update is handled in separate branch below
print(json.dumps(data, ensure_ascii=False, indent=2))
PY
  exit 0
fi

if [ "${args[0]}" = "--arg" ] && [ "${args[1]}" = "file" ] && [ "${args[3]}" = "--arg" ] && [ "${args[4]}" = "uuid" ] && [ "${args[6]}" = "--arg" ] && [ "${args[7]}" = "timestamp" ]; then
  file_key="${args[2]}"
  uuid="${args[5]}"
  timestamp="${args[8]}"
  "$python_exe" - "$target_file" "$file_key" "$uuid" "$timestamp" <<'PY'
import json
import sys
path, file_key, uuid, timestamp = sys.argv[1:5]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
data[file_key] = {"uuid": uuid, "timestamp": timestamp}
print(json.dumps(data, ensure_ascii=False, indent=2))
PY
  exit 0
fi

echo "fake jq: unsupported invocation: $*" >&2
exit 1
EOF

chmod +x "${TMP_DIR}/bin/curl" "${TMP_DIR}/bin/jq" "${TMP_DIR}/bin/python" "${TMP_DIR}/bin/python3"
export PATH="${TMP_DIR}/bin:${PATH}"
export RESULT_SERVER_CLIENT_CERT="${TMP_DIR}/client.crt"
export RESULT_SERVER_CLIENT_KEY="${TMP_DIR}/client.key"
touch "$RESULT_SERVER_CLIENT_CERT" "$RESULT_SERVER_CLIENT_KEY"

pushd "${TMP_DIR}" >/dev/null
if env -u RESULT_SERVER bash "${REPO_DIR}/scripts/result_server/send_results.sh" > missing_result_server.log 2>&1; then
  echo "send_results.sh unexpectedly succeeded without RESULT_SERVER" >&2
  exit 1
fi
grep -q "ERROR: RESULT_SERVER is not set" missing_result_server.log
test ! -f results/server_result_meta.json

if RESULT_SERVER="http://example.invalid" bash "${REPO_DIR}/scripts/result_server/send_results.sh" > insecure_result_server.log 2>&1; then
  echo "send_results.sh unexpectedly succeeded with non-HTTPS RESULT_SERVER" >&2
  exit 1
fi
grep -q "ERROR: RESULT_SERVER must use https://" insecure_result_server.log

export RESULT_SERVER="https://example.invalid"
bash "${REPO_DIR}/scripts/result_server/send_results.sh" >/dev/null
popd >/dev/null

grep -q '"profile_data"' "${TMP_DIR}/results/result0.json"
grep -Eq '"tool":[[:space:]]*"ncu"' "${TMP_DIR}/results/result0.json"
grep -Eq '"level":[[:space:]]*"single"' "${TMP_DIR}/results/result0.json"
grep -Eq '"run_count":[[:space:]]*4' "${TMP_DIR}/results/result0.json"
grep -Eq '"archive_count":[[:space:]]*4' "${TMP_DIR}/results/result0.json"
grep -Eq '"events":[[:space:]]*\[[[:space:]]*\]' "${TMP_DIR}/results/result0.json"
grep -Eq '"ncu_options":[[:space:]]*\[' "${TMP_DIR}/results/result0.json"
grep -Eq '"ncu_report"' "${TMP_DIR}/results/result0.json"
grep -q '"_server_uuid": "11111111-2222-3333-4444-555555555555"' "${TMP_DIR}/results/result0.json"
grep -q '"result0.json"' "${TMP_DIR}/results/server_result_meta.json"
grep -q 'padata0.tgz' "${TMP_DIR}/padata_uploads.log"
grep -q 'padata_k001.tgz' "${TMP_DIR}/padata_uploads.log"
grep -q 'padata_k002.tgz' "${TMP_DIR}/padata_uploads.log"
grep -q 'padata_k003.tgz' "${TMP_DIR}/padata_uploads.log"
grep -q 'artifact_path=results/padata_k001.tgz' "${TMP_DIR}/padata_uploads.log"
grep -q 'artifact_path=results/padata_k002.tgz' "${TMP_DIR}/padata_uploads.log"
grep -q 'artifact_path=results/padata_k003.tgz' "${TMP_DIR}/padata_uploads.log"
test "$(grep -c '/api/ingest/padata' "${TMP_DIR}/padata_uploads.log")" = "4"

mkdir -p "${TMP_DIR}/case413/results"
cp "${TMP_DIR}/results/result0.json" "${TMP_DIR}/case413/results/result0.json"
cp "${TMP_DIR}/results/padata0.tgz" "${TMP_DIR}/case413/results/padata0.tgz"
cp "${TMP_DIR}/results/padata_k001.tgz" "${TMP_DIR}/case413/results/padata_k001.tgz"
cp "${TMP_DIR}/results/padata_k002.tgz" "${TMP_DIR}/case413/results/padata_k002.tgz"
cp "${TMP_DIR}/results/padata_k003.tgz" "${TMP_DIR}/case413/results/padata_k003.tgz"

export FAKE_PADATA_STATUS=413
pushd "${TMP_DIR}/case413" >/dev/null
bash "${REPO_DIR}/scripts/result_server/send_results.sh" > send_results_413.log 2>&1
popd >/dev/null
unset FAKE_PADATA_STATUS

grep -q 'HTTP 413' "${TMP_DIR}/case413/send_results_413.log"
grep -q 'All done.' "${TMP_DIR}/case413/send_results_413.log"
grep -q '"_server_uuid": "11111111-2222-3333-4444-555555555555"' "${TMP_DIR}/case413/results/result0.json"

echo "send_results profile_data test passed"
