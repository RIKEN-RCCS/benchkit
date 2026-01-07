#!/bin/bash
# Debug script for job execution

echo "=== Job Debug Information ==="
echo "Program: $1"
echo "System: $2"
echo "Nodes: $3"
echo "Processes per node: $4"
echo "Threads: $5"
echo "Current working directory: $(pwd)"
echo "Program path: $6"

echo "=== Program Directory Contents ==="
ls -la "$6/" || echo "Cannot list program directory"

echo "=== Current Directory Before Execution ==="
ls -la .

echo "=== About to execute run.sh ==="