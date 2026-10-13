#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
python3 -m unittest discover -s "$SCRIPT_DIR" -p test_estimation_prepare_inputs.py
