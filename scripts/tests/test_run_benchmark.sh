#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
cd "$temporary"
cat > application.sh <<'SH'
echo application-output
echo application-error >&2
printf '%131072s\n' ''
exit "$1"
SH
for expected in 0 23; do
  actual=0
  bash "$ROOT/scripts/run_benchmark.sh" application.sh "$expected" > trace.log 2>&1 || actual=$?
  test "$actual" -eq "$expected"
  test ! -e results/result
  grep -q application-output results/execution.log
  grep -q application-error results/execution.log
  jq -e --argjson code "$expected" '.exit_code == $code and .kind == "benchmark_execution" and
    .status == (if $code == 0 then "completed" else "failed" end) and (.benchkit_commit | length > 0)' results/execution.json >/dev/null
done
# A full log destination must not interrupt the application with SIGPIPE.
rm results/execution.log
ln -s /dev/full results/execution.log
actual=0
bash "$ROOT/scripts/run_benchmark.sh" application.sh 23 > trace.log 2>&1 || actual=$?
test "$actual" -eq 23
jq -e '.exit_code == 23 and .status == "failed"' results/execution.json >/dev/null
grep -q 'execution log could not be stored' trace.log
# No synthetic Result is created when the output directory is unavailable.
rm -r results
touch results
actual=0
bash "$ROOT/scripts/run_benchmark.sh" application.sh 23 > trace.log 2>&1 || actual=$?
test "$actual" -eq 23
grep -q application-output trace.log
grep -q 'records unavailable' trace.log
echo 'benchmark execution evidence tests passed'
