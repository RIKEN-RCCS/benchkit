#!/bin/bash
# --- args checking ---
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <code> <line_number>"
  echo "  <code>: program name (directory under programs/)"
  echo "  <line_number>: line number in programs/<code>/list.csv (1-based, excluding header)"
  echo ""
  echo "Example: $0 myprog 2"
  echo "  This will use the 2nd configuration line from programs/myprog/list.csv"
  exit 1
fi

code=$1
list_csv_line_num=$2

# --- validate line number argument ---
if ! [[ "$list_csv_line_num" =~ ^[0-9]+$ ]]; then
  echo "Error: <line_number> must be a positive integer, got: '$list_csv_line_num'"
  echo "Note: Use line number (1-based), not system name"
  echo "Example: $0 $code 1"
  exit 1
fi

if [ "$list_csv_line_num" -le 0 ]; then
  echo "Error: <line_number> must be greater than 0, got: $list_csv_line_num"
  exit 1
fi

# --- checking dir and list ---
if [ ! -d "programs/$code" ]; then
  echo "Error: programs/$code does not exist"
  echo "Available programs:"
  ls -1 programs/ 2>/dev/null | grep -v "^$" | head -10
  exit 1
fi

list_file="programs/$code/list.csv"
if [ ! -f "$list_file" ]; then
  echo "Error: $list_file does not exist"
  exit 1
fi

# --- check if line number is within range ---
total_lines=$(tail -n +2 "$list_file" | wc -l)
if [ "$list_csv_line_num" -gt "$total_lines" ]; then
  echo "Error: Line $list_csv_line_num does not exist in $list_file"
  echo "Available lines: 1 to $total_lines"
  echo ""
  echo "Contents of $list_file:"
  echo "Line# | Configuration"
  echo "------|-------------"
  echo "  H   | $(head -1 "$list_file")"  # header
  tail -n +2 "$list_file" | nl -v1 -w5 -s' | '  # numbered lines with better formatting
  exit 1
fi

# --- ヘッダを除いて列をチェック ---
line=$(tail -n +2 "$list_file" | sed -n "${list_csv_line_num}p")
if [ -z "$line" ]; then
    echo "Error: Line $list_csv_line_num does not exist in $list_file"
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

# --- 選択された設定を表示 ---
echo "Selected configuration from $list_file (line $list_csv_line_num):"
echo "  $line"
echo ""
echo "Parsed values:"
echo "  system=$system, mode=$mode, queue_group=$queue_group"
echo "  nodes=$nodes, numproc_node=$numproc_node, nthreads=$nthreads, elapse=$elapse"

# --- 投入用スクリプト作成 ---
echo cd $PWD > script.sh
echo bash programs/$code/run.sh $system $nodes >> script.sh

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

# --- MiyabiC ---
if [[ "$system" == "MiyabiC" ]]; then
    echo qsub -q debug-c -l select=${nodes}:ompthreads=$nthreads -l walltime=${elapse} -W group_list=$(groups |awk '{print $2}') \
	 script.sh
    qsub -q debug-c -l select=${nodes}:ompthreads=$nthreads -l walltime=${elapse} -W group_list=$(groups |awk '{print $2}') \
	 script.sh
fi

# --- MiyabiG ---
if [[ "$system" == "MiyabiG" ]]; then
    echo qsub -q debug-g -l select=${nodes}:ompthreads=$nthreads -l walltime=${elapse} -W group_list=$(groups |awk '{print $2}') \
	 script.sh
    qsub -q debug-g -l select=${nodes}:ompthreads=$nthreads -l walltime=${elapse} -W group_list=$(groups |awk '{print $2}') \
	 script.sh
fi

