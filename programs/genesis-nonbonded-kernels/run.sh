#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"

source "${PWD}/scripts/bk_functions.sh"

REPO_DIR="genesis-nonbonded-kernels"
REPO_URL="https://github.com/genesis-release-r-ccs/${REPO_DIR}.git"
BRANCH="${GENESIS_NONBONDED_KERNELS_BRANCH:-main}"
SOURCE_COMMIT="${GENESIS_NONBONDED_KERNELS_SOURCE_COMMIT:-}"
name_list=(Generic Oct Oct_mod1)
dir_list=(Generic Intel Intel_mod1)
input_list=(data_kernel_generic data_kernel_Oct data_kernel_Oct)
resultsdir="${PWD}/results"
artifactsdir="${PWD}/artifacts"
launcher=()

case "$system" in
    Camphor3)
        if [ "$nodes" != 1 ] || [ "$numproc_node" != 1 ]; then
            echo "genesis-nonbonded-kernels requires one node and one process" >&2
            exit 1
        fi
        module switch PrgEnvIntel PrgEnvGCC/2023
        module load gcc/12.2.0
        export OMP_PLACES=cores OMP_PROC_BIND=close
        launcher=(srun --ntasks=1 --cpus-per-task="$nthreads")
        ;;
    Fugaku|FugakuCN) ;;
    *)
        echo "Unknown Running system: $system" >&2
        exit 1
        ;;
esac

# Restore the source commit recorded by the build, including cached builds.
bk_fetch_recorded_source "$REPO_URL" "$REPO_DIR" "$BRANCH" "$SOURCE_COMMIT"
input_commit=$(git -C "$REPO_DIR" rev-parse HEAD)

for i in "${!name_list[@]}"; do
    cp "${artifactsdir}/kernel_${name_list[i]}" "${REPO_DIR}/${dir_list[i]}/kernel"
done

cd "$REPO_DIR"
for input in data_kernel_generic data_kernel_Oct; do
    if [ ! -f "data/$input" ]; then
        # Keep the compressed source input; a failed extraction must not leave
        # a partial file that the next attempt would treat as ready.
        bzip2 -dc "data/$input.bz2" > "data/$input.tmp"
        mv "data/$input.tmp" "data/$input"
    fi
done

export PARALLEL="$nthreads" OMP_NUM_THREADS="$nthreads"
mkdir -p "$resultsdir"
for i in "${!name_list[@]}"; do
    name="${name_list[i]}"
    cd "${dir_list[i]}"
    output="${resultsdir}/log_${name}.txt"
    input="../data/${input_list[i]}"
    bk_record_input --dataset-id "genesis-nonbonded-${input_list[i]}" \
        --file "$input" --repo-url "$REPO_URL" --ref "$BRANCH" \
        --commit "$input_commit" --path "data/${input_list[i]}" --result-exp "$name"
    bk_run --log "$output" -- "${launcher[@]}" ./kernel

    if ! awk '
        /the computed result seems to be OK\./ { ok++ }
        /the computed result is not close enough|Error/ { failed=1 }
        END { exit (ok == 3 && !failed) ? 0 : 1 }
    ' "$output"; then
        echo "Correctness check failed for $name" >&2
        exit 1
    fi
    fom_val=$(awk '/time=/ {print $2; exit}' "$output")
    if ! awk -v value="$fom_val" 'BEGIN {
        exit (value ~ /^[+]?[0-9]+([.][0-9]*)?([eE][+-]?[0-9]+)?$/ && value + 0 > 0) ? 0 : 1
    }'; then
        echo "Invalid kernel time for $name: $fom_val" >&2
        exit 1
    fi
    bk_emit_result --from-log "$output" --fom "$fom_val" --fom-unit s \
        --exp "$name" --nodes "$nodes" --numproc-node "$numproc_node" \
        --nthreads "$nthreads" >> "$resultsdir/result"
    cd ..
done
