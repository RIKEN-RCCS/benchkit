#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON_BIN="${BK_TEST_ESTIMATION_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN=$(command -v "$candidate")
      break
    fi
  done
fi
"${PYTHON_BIN:-python3}" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
"${PYTHON_BIN:-python3}" -B "$SCRIPT_DIR/test_sbd_davidson_ratio.py"
