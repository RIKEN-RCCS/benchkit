#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/project/config" "${TMP_DIR}/project/programs/filterapp"
ln -s "${REPO_DIR}/scripts" "${TMP_DIR}/project/scripts"

cat > "${TMP_DIR}/project/config/system.csv" <<'EOF'
system,mode,tag_build,tag_run,queue,queue_group
FilterSystem,cross,build-tag,run-tag,SLURM_TEST,debug
EOF

cat > "${TMP_DIR}/project/config/queue.csv" <<'EOF'
queue,submit_cmd,template
SLURM_TEST,sbatch,"-p ${queue_group} -t ${elapse} -N ${nodes} --ntasks-per-node=${numproc_node} --cpus-per-task=${nthreads}"
EOF

cat > "${TMP_DIR}/project/config/system_info.csv" <<'EOF'
system,name,cpu_name,cpu_per_node,cpu_cores,gpu_name,gpu_per_node,memory,display_order
FilterSystem,FilterSystem,CPU,1,32,GPU,1,64 GB,1
EOF

cat > "${TMP_DIR}/project/programs/filterapp/list.csv" <<'EOF'
system,enable,nodes,numproc_node,nthreads,elapse
FilterSystem,yes,1,2,3,0:10:00
FilterSystem,yes,2,2,3,0:10:00
FilterSystem,yes,4,2,3,0:10:00
EOF
printf '#!/bin/bash\n' > "${TMP_DIR}/project/programs/filterapp/build.sh"
printf '#!/bin/bash\n' > "${TMP_DIR}/project/programs/filterapp/run.sh"

pushd "${TMP_DIR}/project" >/dev/null

bash scripts/matrix_generate.sh code=filterapp system=FilterSystem nodes=1
grep -q '^filterapp_FilterSystem_N1_P2_T3_run:' .gitlab-ci.generated.yml
grep -q 'name: $CI_COMMIT_BRANCH' .gitlab-ci.generated.yml
if grep -q '^filterapp_FilterSystem_N2_P2_T3_run:' .gitlab-ci.generated.yml; then
  echo "nodes=1 filter must not emit the 2-node fixture job" >&2
  exit 1
fi
if grep -q '^filterapp_FilterSystem_N4_P2_T3_run:' .gitlab-ci.generated.yml; then
  echo "nodes=1 filter must not emit the 4-node fixture job" >&2
  exit 1
fi

bash scripts/matrix_generate.sh code=filterapp system=FilterSystem nodes='2, 4'
if grep -q '^filterapp_FilterSystem_N1_P2_T3_run:' .gitlab-ci.generated.yml; then
  echo "nodes=2,4 filter must not emit the 1-node fixture job" >&2
  exit 1
fi
grep -q '^filterapp_FilterSystem_N2_P2_T3_run:' .gitlab-ci.generated.yml
grep -q '^filterapp_FilterSystem_N4_P2_T3_run:' .gitlab-ci.generated.yml

BK_GITLAB_ENVIRONMENT=develop bash scripts/matrix_generate.sh code=filterapp system=FilterSystem nodes=1
grep -q 'name: "develop"' .gitlab-ci.generated.yml

if BK_GITLAB_ENVIRONMENT='bad scope' bash scripts/matrix_generate.sh code=filterapp system=FilterSystem nodes=1 >/dev/null 2>&1; then
  echo "invalid BK_GITLAB_ENVIRONMENT must fail matrix generation" >&2
  exit 1
fi

popd >/dev/null

echo "matrix generation filter test passed"
