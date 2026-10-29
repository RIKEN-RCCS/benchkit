#!/bin/bash
# Loaded by run.sh after the selected dataset and runtime have been resolved.

record_omnilearned_runtime() {
  local data="$1" image="${2:-}" limit="${BK_OMNILEARNED_OBSERVATION_SECONDS:-30}"
  local status=0 staging="" reason="" snapshot="${RESULTS_DIR}/environment_snapshot_run.json"
  # No unbounded fallback: unavailable observation is preferable to blocking training.
  if ! [[ "$limit" =~ ^[1-9][0-9]*$ ]] || (( ${#limit} > 3 )) || (( limit > 300 )); then
    limit=30
  fi
  if [[ -n "$image" ]]; then
    timeout --kill-after=2 "$limit" python3 "${BK_BENCHKIT_ROOT}/scripts/record_runtime_image.py" "$image" "$snapshot" || status=$?
    if (( status != 0 )); then
      reason=unavailable
      [[ "$status" != 124 && "$status" != 137 ]] || reason=timeout
      timeout --kill-after=2 2 python3 "${BK_BENCHKIT_ROOT}/scripts/record_runtime_image.py" "$image" "$snapshot" "$reason" \
        || echo 'OmniLearned: SIF observation unavailable; preserving execution' >&2
    fi
  fi
  reason=""
  if [[ "${system:-}" == RC_DGXSP ]]; then
    reason=skipped_unified_memory
  elif command -v timeout >/dev/null 2>&1 && staging=$(mktemp -d "${RESULTS_DIR}/.omni-input.XXXXXX"); then
    status=0
    # Isolate partial metadata and temporary hash streams from the final Result.
    timeout --kill-after=2 "$limit" env _BK_DEFAULT_RESULTS_DIR="$staging" \
      BK_INPUT_INFO_FILE="$staging/input_info.json" BK_INPUT_INFO_ITEMS_FILE="$staging/items.jsonl" \
      TMPDIR="$staging" bash -c '
        source "$1/scripts/bk_functions.sh"
        bk_record_input --directory "$2/top" --dataset-id omnilearned-top-staged \
          --recipe "Staged top dataset before launch; not a file consumption trace"
      ' _ "$BK_BENCHKIT_ROOT" "$data" || status=$?
    if (( status != 0 )); then
      reason=interrupted
      [[ "$status" != 124 && "$status" != 137 ]] || reason=timeout
    fi
  else
    reason=unavailable
  fi
  if timeout --kill-after=2 2 python3 "${APP_DIR}/record_dataset.py" \
      "$staging" "$reason" "${data}/top" "${RESULTS_DIR}/input_info.json"; then
    :
  else
    echo 'OmniLearned: dataset observation unavailable; preserving execution' >&2
  fi
  if [[ -n "$staging" ]]; then
    if ! timeout --kill-after=2 2 rm -rf -- "$staging"; then
      echo 'OmniLearned: observation cleanup incomplete; remaining temporary files retained' >&2
    fi
  fi
  return 0
}
