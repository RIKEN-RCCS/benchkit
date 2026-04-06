#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
export OMP_NUM_THREADS=$nthreads

source "${PWD}/scripts/bk_functions.sh"

# Debug output to log file
DEBUG_LOG="../debug_run.log"
echo "=== QWS Run Debug Log ===" > "$DEBUG_LOG"
echo "System: $system" >> "$DEBUG_LOG"
echo "Nodes: $nodes" >> "$DEBUG_LOG"
echo "Current directory: $(pwd)" >> "$DEBUG_LOG"
echo "Date: $(date)" >> "$DEBUG_LOG"

mkdir -p results && > results/result
echo "Results directory created" >> "$DEBUG_LOG"

create_dummy_estimation_artifact() {
    local rel_path="$1"
    local content="$2"
    local full_path="../results/${rel_path}"
    mkdir -p "$(dirname "$full_path")"
    printf '%s\n' "$content" > "$full_path"
}

# print_results: check.sh実行後、FOMを抽出し結果行をstdoutに出力する共通関数
# 引数: $1=出力ファイル, $2=Exp名, $3=numproc_node値
# 使用例: print_results output_file CASE0 1 >> ../results/result
print_results() {
    local outfile=$1
    local exp=$2
    local np=$3
	# 結果の確認をする。
    ./check.sh "$outfile" "data/$exp"
    local fom=$(grep etime "$outfile" | awk 'NR==2{printf("%5.3f\n",$5)}')
    bk_emit_result --fom "$fom" --fom-version DDSolverJacobi --exp "$exp" --nodes "$nodes" --numproc-node "$np" --nthreads "$nthreads"
    # 以下は現状ダミーの値ですが、FOM と整合するように配分しています。
    local section_prepare_rhs
    local section_compute_hopping
    local section_compute_solver
    local section_halo_exchange
    local section_allreduce
    local section_write_result
    local overlap_compute_halo
    section_prepare_rhs=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.16}')
    section_compute_hopping=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.28}')
    section_compute_solver=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.18}')
    section_halo_exchange=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.18}')
    section_allreduce=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.16}')
    section_write_result=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.08}')
    overlap_compute_halo=$(awk -v x="$fom" 'BEGIN {printf "%.3f", x * 0.04}')
    create_dummy_estimation_artifact "estimation_inputs/prepare_rhs_interval.json" "{\"section\":\"prepare_rhs\",\"kind\":\"interval_time\"}"
    create_dummy_estimation_artifact "estimation_inputs/compute_hopping_papi.tgz" "dummy papi archive for compute_hopping"
    create_dummy_estimation_artifact "estimation_inputs/halo_exchange_trace.tgz" "dummy mpi trace archive for halo_exchange"
    create_dummy_estimation_artifact "estimation_inputs/allreduce_trace.tgz" "dummy collective trace archive for allreduce"
    create_dummy_estimation_artifact "estimation_inputs/write_result_interval.json" "{\"section\":\"write_result\",\"kind\":\"interval_time\"}"
    create_dummy_estimation_artifact "estimation_inputs/compute_halo_overlap.json" "{\"overlap\":[\"compute_hopping\",\"halo_exchange\"],\"kind\":\"overlap_time\"}"

    bk_emit_section prepare_rhs "$section_prepare_rhs" interval_time_simple results/estimation_inputs/prepare_rhs_interval.json
    bk_emit_section compute_hopping "$section_compute_hopping" counter_papi_detailed results/estimation_inputs/compute_hopping_papi.tgz
    bk_emit_section compute_solver "$section_compute_solver" counter_papi_detailed results/estimation_inputs/compute_solver_papi.tgz
    bk_emit_section halo_exchange "$section_halo_exchange" trace_mpi_basic results/estimation_inputs/halo_exchange_trace.tgz
    bk_emit_section allreduce "$section_allreduce" trace_collective_logp results/estimation_inputs/allreduce_trace.tgz
    bk_emit_section write_result "$section_write_result" interval_time_simple results/estimation_inputs/write_result_interval.json
    bk_emit_section overlap:compute_hopping,halo_exchange "$overlap_compute_halo" overlap_max_basic results/estimation_inputs/compute_halo_overlap.json --type overlap --members compute_hopping,halo_exchange
}

# results/result の各行は 1 つのベンチマークに対応しています。
# 以下では cd REPO をしているので、後続の処理は ../results/に出力します。
# 新しい FOM（Figure of Merit）を登録する際には、../results/result に行を追加するとともに、
# Performance Analysis (PA) data は ../results/padata[0-9].tgz の形式で保存してください。
#それに対応する PA data を padata[0-9]（0〜9 の番号を付与）として保存してください。

#---------------------------------------------------------------------- 以下を編集します。
#コードを取得。既存ならskip。
echo "Checking for qws directory..." >> "$DEBUG_LOG"
[[ -d qws ]] || git clone https://github.com/RIKEN-LQCD/qws.git
echo "QWS directory status: $(ls -la qws 2>&1)" >> "$DEBUG_LOG"

# build.shで作ったものをartifactsから取ってくる
echo "Copying main executable from artifacts..." >> "$DEBUG_LOG"
echo "Artifacts directory contents:" >> "$DEBUG_LOG"
ls -la artifacts/ >> "$DEBUG_LOG" 2>&1

if [[ -f artifacts/main ]]; then
    cp artifacts/main qws
    echo "Main executable copied successfully" >> "$DEBUG_LOG"
else
    echo "ERROR: artifacts/main not found" >> "$DEBUG_LOG"
    echo "Cannot proceed without main executable" >> "$DEBUG_LOG"
    exit 1
fi

cd qws
echo "Changed to qws directory: $(pwd)" >> "$DEBUG_LOG"
echo "QWS directory contents:" >> "$DEBUG_LOG"
ls -la . >> "$DEBUG_LOG" 2>&1



case "$system" in
    Fugaku|FugakuCN)
	case "$nodes" in
	    1)
		# CASE0
		mpiexec -n 1 ./main 32 6 4 3   1 1 1 1    -1   -1  6 50 > CASE0
		print_results output.${PJM_JOBID}/0/1/stdout.1.0 CASE0 1 >> ../results/result
		# (以下のpadata0.tgzはdummyです。)
		mkdir -p pa
		echo dummy > ./pa/padat.0
		echo dummy > ./pa/padat.1
		echo dummy > ./pa/padat.2
		echo dummy > ./pa/padat.3
		tar -czf ../results/padata0.tgz ./pa
		# CASE1
		mpiexec -n 2 ./main 32 6 4 3   1 1 1 2    -1   -1  6 50 > CASE1
		print_results output.${PJM_JOBID}/0/2/stdout.2.0 CASE1 2 >> ../results/result
		;;
	    2)
		# CASE7
		mpiexec -n 8 ./main 32 6 4 3   1 2 2 2    -1   -1  6 50 > CASE7
		print_results output.${PJM_JOBID}/0/1/stdout.1.0 CASE7 4 >> ../results/result
		;;
	    *)
		echo "Undefined node numbers for system: $system"
		exit 1
		;;
	esac
	;;
    FugakuLN)
	# Dummy FOM for CI private repo access check
	echo 'dummy call for CI test: QWS program: ./main 32 6 4 3   1 1 1 1    -1   -1  6 50'
	bk_emit_result --fom 123.56 --fom-version dummy --exp CheckingPrivateRepo --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ../results/result
	mkdir -p pa
	echo dummy > ./pa/padat.0
	echo dummy > ./pa/padat.1
	echo dummy > ./pa/padat.2
	echo dummy > ./pa/padat.3
	tar -czf ../results/padata0.tgz ./pa
	;;
    FNCX)
	# Dummy FOM for Docker runner pipeline testing
	echo 'dummy call for FNCX Docker runner test'
	bk_emit_result --fom 99.99 --fom-version dummy --exp FNCXTest --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ../results/result
	;;
    RC_GH200)
	module load system/qc-gh200 nvhpc-hpcx/25.9
	mpirun -n 1  --bind-to core --map-by ppr:1:node:PE=72  ./main 32 6 4 3   1 1 1 1    -1   -1  6 50 > CASE0
	print_results CASE0 CASE0 1 >> ../results/result
	#echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_null node_count:$nodes >> ../results/result
	# with confidential key
	#echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamA node_count:$nodes confidential:TeamA>> ../results/result
	#echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamB node_count:$nodes confidential:TeamB>> ../results/result
	#echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamC node_count:$nodes confidential:TeamC>> ../results/result
	#echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamD node_count:$nodes confidential:TeamD>> ../results/result
	#echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamE node_count:$nodes confidential:TeamE>> ../results/result
	#echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamF node_count:$nodes confidential:TeamF>> ../results/result
	;;
    RC_GENOA)
	module load system/genoa  mpi/openmpi-x86_64
	mpirun -n 1  --bind-to core --map-by ppr:1:node:PE=96 ./main 32 6 4 3   1 1 1 1    -1   -1  6 50 > CASE0
	print_results CASE0 CASE0 1 >> ../results/result
	;;
    MiyabiG|MiyabiC)
	mpirun -n 1 ./main 32 6 4 3   1 1 1 1    -1   -1  6 50 > CASE0
	print_results CASE0 CASE0 1 >> ../results/result
	;;
    *)
	echo "Unknown Running system: $system"
	exit 1
	;;
esac

# Log completion
echo "QWS run.sh completed successfully at $(date)" >> "$DEBUG_LOG"
echo "Final results directory contents:" >> "$DEBUG_LOG"
ls -la ../results/ >> "$DEBUG_LOG" 2>&1

# Force NFS sync
cd ..
sync
sleep 5
echo "Forced NFS sync completed" >> debug_run.log
