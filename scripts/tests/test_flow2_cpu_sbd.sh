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
cat > "$tmp/work/artifacts/diag" <<'MOCK'
#!/bin/bash
set -e
[[ $* = *'--adet_comm_size 2'* && $* = *'--bdet_comm_size 2'* ]]
echo 'Elapsed time for davidson 0.5 seconds'
echo 'Elapsed time for mult 0.1 seconds'
echo ' Energy = -76.2429584823075'
MOCK
chmod +x "$tmp/bin/mpirun" "$tmp/work/artifacts/diag"
printf 'fixture\n' > "$tmp/work/artifacts/fcidump.txt"
printf 'fixture\n' > "$tmp/work/artifacts/h2o-1em4-alpha.txt"
(
 cd "$tmp/work"
 PATH="$tmp/bin:$PATH" bash programs/sbd/run.sh Flow2_Type1 1 4 12
 grep -q 'FOM:0.5' results/result
 grep -q 'H2O-1em4' results/result
 if PATH="$tmp/bin:$PATH" bash programs/sbd/run.sh Flow2_Type1 1 1 48; then
   echo 'Unsupported rank count accepted' >&2; exit 1
 fi
)
echo 'Flow2 SBD CPU route test passed'
