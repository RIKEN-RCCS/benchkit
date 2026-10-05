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
NativeSystem,native,,compute-tag,PBS_NATIVE,accelerator
CpuSystem,cross,build-tag,compute-tag,PBS_CPU,cpu
EOF

cat > "${TMP_DIR}/project/config/queue.csv" <<'EOF'
queue,submit_cmd,template
SLURM_TEST,sbatch,"-p ${queue_group} -t ${elapse} -N ${nodes} --ntasks-per-node=${numproc_node} --cpus-per-task=${nthreads}"
PBS_NATIVE,qsub,"-q ${queue_group} -l select=${nodes}:ncpus=${cpu_cores_per_node}:ngpus=${gpu_per_node}:mpiprocs=${numproc_node}:ompthreads=${nthreads} -l walltime=${elapse}"
PBS_CPU,qsub,"-q ${queue_group} -l select=${nodes}:ncpus=${cpu_cores_per_node}:mpiprocs=${numproc_node}:ompthreads=${nthreads} -l walltime=${elapse}"
EOF

cat > "${TMP_DIR}/project/config/system_info.csv" <<'EOF'
system,name,cpu_name,cpu_per_node,cpu_cores,gpu_name,gpu_per_node,memory,display_order
FilterSystem,FilterSystem,CPU,1,32,GPU,1,64 GB,1
NativeSystem,NativeSystem,CPU,2,7,GPU,3,64 GB,2
CpuSystem,CpuSystem,CPU,2,9,-,-,64 GB,3
EOF

cat > "${TMP_DIR}/project/programs/filterapp/list.csv" <<'EOF'
system,enable,nodes,numproc_node,nthreads,elapse
FilterSystem,yes,1,2,3,0:10:00
FilterSystem,yes,2,2,3,0:10:00
FilterSystem,yes,4,2,3,0:10:00
NativeSystem,yes,1,2,3,0:10:00
NativeSystem,yes,1,1,4,0:10:00
CpuSystem,yes,1,3,2,0:10:00
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

bash scripts/matrix_generate.sh code=filterapp system=NativeSystem numproc_node=2
grep -q '^filterapp_NativeSystem_N1_P2_T3_build_run:' .gitlab-ci.generated.yml
grep -q '^  tags: \["compute-tag"\]' .gitlab-ci.generated.yml
grep -q 'select=1:ncpus=14:ngpus=3:mpiprocs=2:ompthreads=3' .gitlab-ci.generated.yml
grep -q '^  needs: \["filterapp_NativeSystem_N1_P2_T3_build_run"\]' .gitlab-ci.generated.yml
if grep -Eq '^  stage: (build|run)$' .gitlab-ci.generated.yml; then
  echo "native mode must not create separate build or run jobs" >&2
  exit 1
fi
awk '
  /bash scripts\/build_with_cache.sh filterapp NativeSystem programs\/filterapp/ { build = NR }
  /bash programs\/filterapp\/run.sh NativeSystem 1 2 3/ { run = NR }
  END { exit !(build && run > build) }
' .gitlab-ci.generated.yml

bash scripts/matrix_generate.sh code=filterapp system=NativeSystem numproc_node=1
grep -q 'select=1:ncpus=14:ngpus=3:mpiprocs=1:ompthreads=4' .gitlab-ci.generated.yml

bash scripts/matrix_generate.sh code=filterapp system=CpuSystem
grep -q '^filterapp_CpuSystem_build:' .gitlab-ci.generated.yml
grep -q '^filterapp_CpuSystem_N1_P3_T2_run:' .gitlab-ci.generated.yml
grep -q 'select=1:ncpus=18:mpiprocs=3:ompthreads=2' .gitlab-ci.generated.yml
if grep -q 'ngpus=' .gitlab-ci.generated.yml; then
  echo "CPU-only template must not request GPUs" >&2
  exit 1
fi

cat > config/system_info.csv <<'EOF'
system,name,cpu_name,cpu_per_node,cpu_cores,gpu_name,gpu_per_node,memory,display_order
NativeSystem,NativeSystem,CPU,2,-,GPU,3,64 GB,1
EOF
if bash scripts/matrix_generate.sh code=filterapp system=NativeSystem >/dev/null 2>&1; then
  echo "full-node CPU template must reject missing core counts" >&2
  exit 1
fi

popd >/dev/null

echo "matrix generation filter test passed"
