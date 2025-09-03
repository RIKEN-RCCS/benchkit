#!/bin/bash
# --- args checking ---
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <code> <system number of programs/<code>/list.csv>"
  echo "Example: $0 myprog 2"
  exit 1
fi

code=$1
sys=$2

# --- checking dir and list ---
if [ ! -d "programs/$code" ]; then
  echo "Error: programs/$code does not exist"
  exit 1
fi

list_file="programs/$code/list.csv"
if [ ! -f "$list_file" ]; then
  echo "Error: $list_file does not exist"
  exit 1
fi

# --- ヘッダを除いて列をチェック ---
line=$(tail -n +2 "$list_file" | sed -n "${sys}p")
if [ -z "$line" ]; then
    echo "Error: Line $sys does not exist in $list_file"
    exit 1
fi

# --- カンマ区切りで配列に格納 ---
IFS=, read -r -a cols <<< "$line"

# --- 先頭に # があれば通知 ---
if [[ "${cols[0]}" == \#* ]]; then
    echo "Notice: Line $line_number starts with '#' : $line"
    exit 1
fi

# --- 変数に格納 ---
system="${cols[0]}"
mode="${cols[1]}"
queue_group="${cols[2]}"
nodes="${cols[3]}"
numproc_node="${cols[4]}"
nthreads="${cols[5]}"
elapse="${cols[6]}"

# --- 値を表示 ---
echo "system=$system, mode=$mode, queue_group=$queue_group, nodes=$nodes, numproc_node=$numproc_node, nthreads=$nthreads, elapse=$elapse"

# --- 投入用スクリプト作成 ---
echo bash programs/$code/run.sh $system $nodes > script.sh

# --- FugakuLN は submit テスト対象外 ---
if [[ "$system" == "FugakuLN" ]]; then
    echo "Notice: system=$system → submit test will NOT be performed."
    exit 1
fi



# --- Fugaku or FugakuCN ---
if [[ "$system" == "Fugaku" || "$system" == "FugakuCN" ]]; then
echo pjsub -L rscunit=rscunit_ft01,rscgrp=$queue_group,node=$nodes,elapse=$elapse \
      --mpi max-proc-per-node=$numproc_node \
      -S -x PJM_LLIO_GFSCACHE=/vol0004:/vol0003 \
      script.sh

pjsub -L rscunit=rscunit_ft01,rscgrp=$queue_group,node=$nodes,elapse=$elapse \
      --mpi max-proc-per-node=$numproc_node \
      -S -x PJM_LLIO_GFSCACHE=/vol0004:/vol0003 \
      script.sh
fi

# --- RC_GH200 ---
if [[ "$system" == "RC_GH200" ]]; then
    echo sbatch -p qc-gh200 -N $nodes -t $elapse --ntasks-per-node=${numproc_node} --cpus-per-task=$nthreads \
	 --wrap="bash programs/$code/run.sh $system $nodes"
    sbatch -p qc-gh200 -N $nodes -t $elapse --ntasks-per-node=${numproc_node} --cpus-per-task=$nthreads \
	   --wrap="bash programs/${code}/run.sh $system $nodes"
fi

