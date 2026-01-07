#!/bin/bash
# Check results directory after job execution

echo "=== Results Check ==="
echo "Exit code of previous command: $1"

if [[ -d results ]]; then
    echo "Results directory found:"
    ls -la results/
else
    echo "Results directory NOT found"
    echo "Current directory contents:"
    ls -la . | head -10
fi