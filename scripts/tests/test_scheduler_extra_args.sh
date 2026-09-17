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
test "$(get_scheduler_extra_args Fugaku)" = "-g rkp00010"
test "$(get_scheduler_extra_args FugakuCN)" = "-g rkp00010"
test "$(get_scheduler_extra_args RC_GH200)" = ""

export BK_ALLOCATION_PROJECT_ID="rkp00010 --qos=debug"
if get_scheduler_extra_args RIKYU >/dev/null 2>&1; then
    echo "RIKYU must reject invalid BK_ALLOCATION_PROJECT_ID" >&2
    exit 1
fi
export BK_ALLOCATION_PROJECT_ID="rkp00010"

export BK_SCHEDULER_EXTRA_ARGS_RIKYU="--account=explicit-rikyu"
test "$(get_scheduler_extra_args RIKYU)" = "--account=explicit-rikyu"

unset BK_SCHEDULER_EXTRA_ARGS_RIKYU
export BK_SCHEDULER_EXTRA_ARGS="--account=global"
test "$(get_scheduler_extra_args RIKYU)" = "--account=global"
test "$(get_scheduler_extra_args Fugaku)" = "--account=global"

tmpdir=""
project_dir=""
estimate_tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir" "$estimate_tmpdir"' EXIT

mkdir -p "$estimate_tmpdir/app"
if has_estimate_script "$estimate_tmpdir/app"; then
    echo "directory without estimate.sh must not be estimate-enabled" >&2
    exit 1
fi
touch "$estimate_tmpdir/app/estimate.sh"
has_estimate_script "$estimate_tmpdir/app"
touch "$estimate_tmpdir/app/estimate.disabled"
if has_estimate_script "$estimate_tmpdir/app"; then
    echo "estimate.disabled must disable estimate.sh" >&2
    exit 1
fi

tmpdir=$(mktemp -d)
project_dir="$tmpdir/project"

mkdir -p "$project_dir/config" "$project_dir/programs/schedulerapp"
ln -s "${REPO_DIR}/scripts" "$project_dir/scripts"

cat > "$project_dir/config/system.csv" <<'EOF'
system,mode,tag_build,tag_run,queue,queue_group
RC_GH200,native,,,SLURM_RC,gh200
Fugaku,cross,,,FJ,small
EOF

cat > "$project_dir/config/system_info.csv" <<'EOF'
system,name,cpu_name,cpu_per_node,cpu_cores,gpu_name,gpu_per_node,memory,display_order
RC_GH200,RC_GH200,CPU,1,72,GPU,1,120 GB,1
Fugaku,Fugaku,CPU,1,48,-,-,32 GB,2
EOF

cat > "$project_dir/programs/schedulerapp/list.csv" <<'EOF'
system,enable,nodes,numproc_node,nthreads,elapse
RC_GH200,yes,1,1,1,0:05:00
Fugaku,yes,1,2,3,0:05:00
EOF
printf '#!/bin/bash\n' > "$project_dir/programs/schedulerapp/build.sh"
printf '#!/bin/bash\n' > "$project_dir/programs/schedulerapp/run.sh"

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
unset BK_SCHEDULER_EXTRA_ARGS_Fugaku
unset BK_SCHEDULER_EXTRA_ARGS_RC_GH200

pushd "$project_dir" >/dev/null
bash scripts/test_submit_build.sh schedulerapp 1 >/dev/null
if grep -q -- "--account=rkp00010" "$BK_TEST_SBATCH_ARGS_FILE"; then
    echo "RC_GH200 must not derive --account from BK_ALLOCATION_PROJECT_ID" >&2
    exit 1
fi

export BK_SCHEDULER_EXTRA_ARGS_RC_GH200="--account=explicit-rc"
bash scripts/test_submit_build.sh schedulerapp 1 >/dev/null
grep -q -- "--account=explicit-rc" "$BK_TEST_SBATCH_ARGS_FILE"

cat >"$tmpdir/pjsub" <<'SCRIPT'
#!/bin/bash
printf '%s\n' "$*" >"${BK_TEST_PJSUB_ARGS_FILE:?}"
SCRIPT
chmod +x "$tmpdir/pjsub"

export BK_TEST_PJSUB_ARGS_FILE="$tmpdir/pjsub.args"
export BK_ALLOCATION_PROJECT_ID="ra000009"
unset BK_SCHEDULER_EXTRA_ARGS
unset BK_SCHEDULER_EXTRA_ARGS_Fugaku

bash scripts/test_submit.sh schedulerapp 2 >/dev/null
grep -q -- "-g ra000009" "$BK_TEST_PJSUB_ARGS_FILE"

unset BK_ALLOCATION_PROJECT_ID
bash scripts/test_submit.sh schedulerapp 2 >/dev/null
if grep -q -- "-g" "$BK_TEST_PJSUB_ARGS_FILE"; then
    echo "Fugaku must not pass -g when BK_ALLOCATION_PROJECT_ID is unset" >&2
    exit 1
fi
popd >/dev/null

popd >/dev/null

echo "scheduler extra args test passed"
