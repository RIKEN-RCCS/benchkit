#!/bin/bash
# Shared root and recording context initialization.

if [ -z "${BK_BENCHKIT_ROOT:-}" ]; then
  BK_BENCHKIT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
  export BK_BENCHKIT_ROOT
fi

if [ -z "${_BK_WORKFLOW_SESSION_ID:-}" ]; then
  printf -v _BK_WORKFLOW_EPOCH '%(%s)T' -1
  export _BK_WORKFLOW_SESSION_ID="${_BK_WORKFLOW_EPOCH}-${BASHPID}-${RANDOM}"
fi

# Capture the caller's root once; applications can change cwd without metadata exports.
_BK_DEFAULT_RESULTS_DIR="${_BK_DEFAULT_RESULTS_DIR:-${PWD}/results}"
export _BK_DEFAULT_RESULTS_DIR
