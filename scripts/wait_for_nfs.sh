#!/bin/bash
# Wait for NFS file synchronization
# Usage: bash scripts/wait_for_nfs.sh <directory_or_file>

target="${1:-results}"

echo "Flushing NFS cache..."
sync

echo "Waiting for NFS synchronization of: $target"
echo "Working directory: $(pwd)"
echo "Initial directory listing:"
ls -la . 2>/dev/null || echo "Cannot list current directory"

max_wait=600  # Increased to 10 minutes
wait_time=0

while [[ $wait_time -lt $max_wait ]]; do
  # Force filesystem sync every 30 seconds
  if [[ $((wait_time % 30)) -eq 0 ]]; then
    echo "Forcing filesystem sync at ${wait_time}s..."
    sync
    sleep 2
  fi
  
  if [[ -e "$target" ]]; then
    # If target is results directory, also check for completion marker and JSON files
    if [[ "$target" == "results" && -d "results" ]]; then
      echo "Results directory found, checking contents..."
      ls -la results/ 2>/dev/null || echo "Cannot list results directory"
      
      # Check for completion marker first
      if [[ -f "results/.complete" ]]; then
        json_count=$(ls results/*.json 2>/dev/null | wc -l)
        if [[ $json_count -gt 0 ]]; then
          echo "Target found: $target (with completion marker and $json_count JSON files)"
          echo "Final results directory contents:"
          ls -la results/
          # Additional wait to ensure all files are visible
          sleep 15
          sync
          echo "NFS synchronization complete"
          exit 0
        else
          echo "Completion marker found but no JSON files yet... ($wait_time/$max_wait seconds)"
        fi
      else
        echo "Results directory found but no completion marker yet... ($wait_time/$max_wait seconds)"
        echo "Current results contents:"
        ls -la results/ 2>/dev/null || echo "Results directory empty or inaccessible"
      fi
    else
      echo "Target found: $target"
      # Additional wait to ensure all files are visible
      sleep 10
      sync
      echo "NFS synchronization complete"
      exit 0
    fi
  else
    if [[ $((wait_time % 30)) -eq 0 ]]; then
      echo "Still waiting for $target... ($wait_time/$max_wait seconds)"
      echo "Current directory contents:"
      ls -la . 2>/dev/null | head -10
    fi
  fi
  
  sleep 5
  wait_time=$((wait_time + 5))
done

echo "WARNING: Target not found after $max_wait seconds: $target"
echo "Final directory contents:"
ls -la . 2>/dev/null || echo "Cannot list current directory"
if [[ "$target" == "results" ]]; then
  echo "Results directory status:"
  ls -la results/ 2>/dev/null || echo "Results directory not found"
fi
echo "Filesystem information:"
df -h . 2>/dev/null || echo "Cannot get filesystem info"
exit 0  # Don't fail the job, just warn
