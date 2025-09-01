#!/bin/bash
set -e
system="$1"
nodes="$2"
mkdir -p results && > results/result

#----------------------------------------------------------------------
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
	echo 'dummy call for CB test: QWS program: ./main 32 6 4 3   1 1 1 1    -1   -1  6 50'
	echo FOM:123.56 FOM_version:dummy Exp:dummy > ../results/result
	
	mkdir -p pa
	echo dummy > ./pa/padat.0
	echo dummy > ./pa/padat.1
	echo dummy > ./pa/padat.2
	echo dummy > ./pa/padat.3
	tar -czf ../results/padata0.tgz ./pa
	ls ../results/
	;;
    *)
	echo "Unknown Running system: $system"
	exit 1
	;;
esac
