#!/bin/bash
# Wait for NFS file synchronization
# Usage: bash scripts/wait_for_nfs.sh <directory_or_file>

target="${1:-results}"

echo "Flushing NFS cache..."
sync

echo "Waiting for NFS synchronization of: $target"
max_wait=60
wait_time=0

while [[ $wait_time -lt $max_wait ]]; do
  if [[ -e "$target" ]]; then
    echo "Target found: $target"
    # Additional wait to ensure all files are visible
    sleep 5
    sync
    echo "NFS synchronization complete"
    exit 0
  fi
  
  echo "Waiting... ($wait_time/$max_wait seconds)"
  sleep 5
  wait_time=$((wait_time + 5))
done

echo "WARNING: Target not found after $max_wait seconds: $target"
exit 0  # Don't fail the job, just warn
