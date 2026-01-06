#!/bin/bash
# Wait for NFS file synchronization
# Usage: bash scripts/wait_for_nfs.sh <directory_or_file>

target="${1:-results}"

echo "Flushing NFS cache..."
sync

echo "Waiting for NFS synchronization of: $target"
max_wait=120  # Increased to 2 minutes
wait_time=0

while [[ $wait_time -lt $max_wait ]]; do
  if [[ -e "$target" ]]; then
    # If target is results directory, also check for JSON files
    if [[ "$target" == "results" && -d "results" ]]; then
      json_count=$(ls results/*.json 2>/dev/null | wc -l)
      if [[ $json_count -gt 0 ]]; then
        echo "Target found: $target (with $json_count JSON files)"
        # Additional wait to ensure all files are visible
        sleep 10
        sync
        echo "NFS synchronization complete"
        exit 0
      else
        echo "Results directory found but no JSON files yet... ($wait_time/$max_wait seconds)"
      fi
    else
      echo "Target found: $target"
      # Additional wait to ensure all files are visible
      sleep 5
      sync
      echo "NFS synchronization complete"
      exit 0
    fi
  else
    echo "Waiting... ($wait_time/$max_wait seconds)"
  fi
  
  sleep 5
  wait_time=$((wait_time + 5))
done

echo "WARNING: Target not found after $max_wait seconds: $target"
if [[ "$target" == "results" ]]; then
  echo "Directory contents:"
  ls -la results/ 2>/dev/null || echo "Results directory not found"
fi
exit 0  # Don't fail the job, just warn
