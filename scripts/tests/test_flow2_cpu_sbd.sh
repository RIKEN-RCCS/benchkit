#!/bin/bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/work/artifacts" "$tmp/work/programs"
ln -s "$root/scripts" "$tmp/work/scripts"
ln -s "$root/programs/sbd" "$tmp/work/programs/sbd"
module() { :; }
export -f module
cat > "$tmp/bin/mpirun" <<'MOCK'
#!/bin/bash
set -e
[[ $1 = -np && $2 = 4 && ${MKL_NUM_THREADS:-} = 1 && ${OMP_NUM_THREADS:-} = 12 ]]
shift 2
"$@"
MOCK
cat > "$tmp/bin/srun" <<'MOCK'
#!/bin/bash
set -e
[[ $1 = -n && $2 = 4 && $3 = --ntasks-per-node=4 && $4 = --cpus-per-task=12 ]]
[[ ${MKL_NUM_THREADS:-} = 1 && ${OMP_NUM_THREADS:-} = 12 ]]
[[ ${OMP_PLACES:-} = cores && ${OMP_PROC_BIND:-} = close ]]
shift 4
"$@"
MOCK
cat > "$tmp/work/artifacts/diag" <<'MOCK'
#!/bin/bash
set -e
[[ $* = *'--adet_comm_size 2'* && $* = *'--bdet_comm_size 2'* ]]
echo 'Elapsed time for davidson 0.5 seconds'
echo 'Elapsed time for mult 0.1 seconds'
echo ' Energy = -76.2429584823075'
MOCK
chmod +x "$tmp/bin/srun" "$tmp/bin/mpirun" "$tmp/work/artifacts/diag"
printf 'fixture\n' > "$tmp/work/artifacts/fcidump.txt"
printf 'fixture\n' > "$tmp/work/artifacts/h2o-1em4-alpha.txt"
(
 cd "$tmp/work"
 for system in Flow2_Type1 Camphor3; do
 PATH="$tmp/bin:$PATH" bash programs/sbd/run.sh "$system" 1 4 12
 grep -q 'FOM:0.5' results/result
 grep -q 'H2O-1em4' results/result
 jq -e '.inputs | length == 2' results/input_info.json >/dev/null
 for input in fcidump.txt h2o-1em4-alpha.txt; do
   digest=$(sha256sum "sbd_run/$input" | awk '{print $1}')
   jq -e --arg digest "$digest" --arg exp H2O-1em4 \
     '[.inputs[] | select(.result_exp == $exp) | .observation_capture.manifest.files[].sha256] | index($digest) != null' \
     results/input_info.json >/dev/null
 done
 if PATH="$tmp/bin:$PATH" bash programs/sbd/run.sh "$system" 1 1 48; then
   echo 'Unsupported rank count accepted' >&2; exit 1
 fi
 done
)
echo 'Flow2 and Camphor3 SBD CPU routes passed'
