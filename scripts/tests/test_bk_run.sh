#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
"${PYTHON_BIN:-python3}" "${SCRIPT_DIR}/test_run_output.py"
