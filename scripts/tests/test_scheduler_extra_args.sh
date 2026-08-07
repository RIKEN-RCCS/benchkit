#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

pushd "${REPO_DIR}" >/dev/null
source ./scripts/job_functions.sh

export BK_ALLOCATION_PROJECT_ID="rkp00010"
unset BK_SCHEDULER_EXTRA_ARGS
unset BK_SCHEDULER_EXTRA_ARGS_RIKYU
unset BK_SCHEDULER_EXTRA_ARGS_RC_GH200

test "$(get_scheduler_extra_args RIKYU)" = "--account=rkp00010"
test "$(get_scheduler_extra_args RC_GH200)" = ""
test "$(get_scheduler_extra_args Fugaku)" = ""

export BK_SCHEDULER_EXTRA_ARGS_RIKYU="--account=explicit-rikyu"
test "$(get_scheduler_extra_args RIKYU)" = "--account=explicit-rikyu"

unset BK_SCHEDULER_EXTRA_ARGS_RIKYU
export BK_SCHEDULER_EXTRA_ARGS="--account=global"
test "$(get_scheduler_extra_args RIKYU)" = "--account=global"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

cat >"$tmpdir/sbatch" <<'SCRIPT'
#!/bin/bash
printf '%s\n' "$*" >"${BK_TEST_SBATCH_ARGS_FILE:?}"
SCRIPT
chmod +x "$tmpdir/sbatch"

export PATH="$tmpdir:$PATH"
export BK_TEST_SBATCH_ARGS_FILE="$tmpdir/sbatch.args"
export BK_ALLOCATION_PROJECT_ID="rkp00010"
unset BK_SCHEDULER_EXTRA_ARGS
unset BK_SCHEDULER_EXTRA_ARGS_RIKYU
unset BK_SCHEDULER_EXTRA_ARGS_RC_GH200

bash scripts/test_submit_build.sh qws 5 >/dev/null
if grep -q -- "--account=rkp00010" "$BK_TEST_SBATCH_ARGS_FILE"; then
    echo "RC_GH200 must not derive --account from BK_ALLOCATION_PROJECT_ID" >&2
    exit 1
fi

export BK_SCHEDULER_EXTRA_ARGS_RC_GH200="--account=explicit-rc"
bash scripts/test_submit_build.sh qws 5 >/dev/null
grep -q -- "--account=explicit-rc" "$BK_TEST_SBATCH_ARGS_FILE"

popd >/dev/null

echo "scheduler extra args test passed"
