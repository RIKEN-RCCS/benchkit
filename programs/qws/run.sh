#!/bin/bash
set -e
system="$1"
nodes="$2"
mkdir -p results && > results/result


# results/result の各行は 1 つのベンチマークに対応しています。
# 以下では cd REPO をしているので、後続の処理は ../results/に出力します。
# 新しい FOM（Figure of Merit）を登録する際には、../results/result に行を追加するとともに、
# Performance Analysis (PA) data は ../results/padata[0-9].tgz の形式で保存してください。
#それに対応する PA data を padata[0-9]（0〜9 の番号を付与）として保存してください。

#---------------------------------------------------------------------- 以下を編集します。
#コードを取得。既存ならskip。
[[ -d qws ]] || git clone https://github.com/RIKEN-LQCD/qws.git
# build.shで作ったものをartifactsから取ってくる
cp artifacts/main qws

cd qws



case "$system" in
    Fugaku|FugakuCN)
	case "$nodes" in
	    1)
		# CASE0
		mpiexec -n 1 ./main 32 6 4 3   1 1 1 1    -1   -1  6 50 > CASE0
		./check.sh output.${PJM_JOBID}/0/1/stdout.1.0 data/CASE0
		FOM=$(grep etime output.${PJM_JOBID}/0/1/stdout.1.0 | awk 'NR==2{printf("%5.3f\n",$5)}')
		echo FOM:$FOM FOM_version:DDSolverJacobi Exp:CASE0 node_count:$nodes >> ../results/result
		# CASE1
		mpiexec -n 2 ./main 32 6 4 3   1 1 1 2    -1   -1  6 50 > CASE1
		./check.sh output.${PJM_JOBID}/0/2/stdout.2.0 data/CASE1
		FOM=$(grep etime output.${PJM_JOBID}/0/2/stdout.2.0 | awk 'NR==2{printf("%5.3f\n",$5)}')
		echo FOM:$FOM FOM_version:DDSolverJacobi Exp:CASE1 node_count:$nodes >> ../results/result
		;;
	    2)
		# CASE7
		mpiexec -n 8 ./main 32 6 4 3   1 2 2 2    -1   -1  6 50 > CASE7
		./check.sh output.${PJM_JOBID}/0/1/stdout.1.0 data/CASE7
		FOM=$(grep etime output.${PJM_JOBID}/0/1/stdout.1.0 | awk 'NR==2{printf("%5.3f\n",$5)}')
		echo FOM:$FOM FOM_version:DDSolverJacobi Exp:CASE7 node_count:$nodes >> ../results/result
		;;
	    *)
		echo "Unknown Running system: $system"
		exit 1
		;;
	esac
	;;
    FugakuLN)
	export OMP_NUM_THREADS=12
	./main 32 6 4 3   1 1 1 1    -1   -1  6 50 > CASE0
	./check.sh CASE0 data/CASE0
	FOM=$(grep etime CASE0 | awk 'NR==2{printf("%5.3f\n",$5)}')
	echo FOM:$FOM FOM_version:DDSolverJacobi Exp:CASE0 node_count:$nodes >> ../results/result
	
	# (以下のpadata0.tgzはdummyです。)
	mkdir -p pa
	echo dummy > ./pa/padat.0
	echo dummy > ./pa/padat.1
	echo dummy > ./pa/padat.2
	echo dummy > ./pa/padat.3
	tar -czf ../results/padata0.tgz ./pa
	#ls ../results/
	;;
    RC_GH200)
	echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_null node_count:$nodes >> ../results/result
	# with confidential key
	echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamA node_count:$nodes confidential:TeamA>> ../results/result
	echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamB node_count:$nodes confidential:TeamB>> ../results/result
	echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamC node_count:$nodes confidential:TeamC>> ../results/result
	echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamD node_count:$nodes confidential:TeamD>> ../results/result
	echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamE node_count:$nodes confidential:TeamE>> ../results/result
	echo FOM:11.22 FOM_version:dummy_qc-gh200 Exp:confidential_TeamF node_count:$nodes confidential:TeamF>> ../results/result
	;;
     MiyabiG|MiyabiC)
	mpirun -n 1 ./main 32 6 4 3   1 1 1 1    -1   -1  6 50 > CASE0
	./check.sh CASE0 data/CASE0
	FOM=$(grep etime CASE0 | awk 'NR==2{printf("%5.3f\n",$5)}')
	echo FOM:$FOM FOM_version:DDSolverJacobi Exp:CASE0 node_count:$nodes >> ../results/result
	;;
    *)
	echo "Unknown Running system: $system"
	exit 1
	;;
esac
