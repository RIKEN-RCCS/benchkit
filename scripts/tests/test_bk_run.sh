#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "${SCRIPT_DIR}/shell_test_parts.sh"
shell_test_parts_init "${BASH_SOURCE[0]}" "$@"
"${PYTHON_BIN:-python3}" "${SCRIPT_DIR}/test_run_output.py" --part "$TEST_PART"
