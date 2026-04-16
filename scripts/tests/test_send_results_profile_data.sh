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
  "source_info": null
}
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

cat > "${TMP_DIR}/bin/curl" <<'EOF'
#!/bin/bash
set -euo pipefail
if printf '%s\n' "$*" | grep -q '/api/ingest/result'; then
  printf '%s\n' '{"id":"11111111-2222-3333-4444-555555555555","timestamp":"20260413_230000"}'
  exit 0
fi
if printf '%s\n' "$*" | grep -q '/api/ingest/padata'; then
  printf '%s\n' '{"status":"uploaded"}'
  exit 0
fi
printf '%s\n' '{"status":"ok"}'
EOF

cat > "${TMP_DIR}/bin/python" <<'EOF'
#!/bin/bash
set -euo pipefail
if [ "${1:-}" = "scripts/validate_result_quality.py" ]; then
  printf '%s\n' "$*" > "${TMP_DIR}/validator_invocation.txt"
  exit 0
fi
echo "fake python: unsupported invocation: $*" >&2
exit 1
EOF

cat > "${TMP_DIR}/bin/python3" <<'EOF'
#!/bin/bash
set -euo pipefail
exec "${TMP_DIR}/bin/python" "$@"
EOF

cat > "${TMP_DIR}/bin/jq" <<'EOF'
#!/bin/bash
set -euo pipefail
python_exe="/c/Users/yoshi/AppData/Local/Programs/Python/Python312/python.exe"

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
        "events": [run.get("event") for run in data.get("runs", []) if run.get("event")],
        "report_kinds": sorted({rep.get("kind") for run in data.get("runs", []) for rep in run.get("reports", []) if rep.get("kind")}),
    }
    print(json.dumps(summary))
    sys.exit(0)
raise SystemExit(1)
PY
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
export RESULT_SERVER="https://example.invalid"
export RESULT_SERVER_KEY="dummy"
export BK_RESULT_QUALITY_VALIDATE="true"
export BK_RESULT_QUALITY_FAIL_ON="none"

pushd "${TMP_DIR}" >/dev/null
bash "${REPO_DIR}/scripts/result_server/send_results.sh" >/dev/null
popd >/dev/null

grep -q 'scripts/validate_result_quality.py results --fail-on none' "${TMP_DIR}/validator_invocation.txt"
grep -q '"profile_data"' "${TMP_DIR}/results/result0.json"
grep -q '"tool": "fapp"' "${TMP_DIR}/results/result0.json"
grep -q '"level": "single"' "${TMP_DIR}/results/result0.json"
grep -q '"run_count": 1' "${TMP_DIR}/results/result0.json"
grep -q '"_server_uuid": "11111111-2222-3333-4444-555555555555"' "${TMP_DIR}/results/result0.json"
grep -q '"result0.json"' "${TMP_DIR}/results/server_result_meta.json"

echo "send_results profile_data test passed"
