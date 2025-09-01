#!/bin/bash
#set -euo pipefail

if [ ! -d results ] || [ ! -f results/result ]; then
  echo "Error: results/ or results/result not found"
  exit 1
fi

if ! grep -q "FOM" results/result; then
  echo "Error: results/result does not contain FOM"
  exit 1
fi

ls results/
cat results/result

code=$1
system=$2
node_count='how_many'



# --- system information ---
case "$system" in
  Fugaku|FugakuCN)
    cpu_name="A64FX"
    gpu_name="-"
    cpu_cores=48
    cpus_per_node=1
    gpus_per_node=0
    ;;
  *)
    echo "Unknown $system"
    gcc_version=$(gcc --version | head -n1 | sed 's/"/\\"/g')
    cpu_name=$(grep -m1 "model name" /proc/cpuinfo | cut -d':' -f2 | sed 's/^ *//;s/"/\\"/g')
    gpu_name=""
    cpu_cores=$(nproc)
    cpus_per_node=""
    gpus_per_node=""
    ;;
esac

uname_info=$(uname -a | sed 's/"/\\"/g')

#echo $uname_info




i=0

while IFS= read -r line; do
  # --- From results/result ---
  if [[ "$line" != *FOM* ]]; then
    continue
  fi


  # FOM
  fom=$(echo $line | grep -Eo 'FOM:[ ]*[0-9.]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
  if [ -z "$fom" ]; then
    fom=null
  fi

  # node_count
  node_count_line=$(echo $line | grep -Eo 'node_count:[ ]*[0-9]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')

  if [ -n "$node_count_line" ]; then
    node_count=${node_count_line}
  fi

  # cpus_per_node_line
  cpus_per_node_line=$(echo $line | grep -Eo 'cpus_per_node:[ ]*[0-9]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')

  if [ -n "$cpus_per_node_line" ]; then
    cpus_per_node=${cpus_per_node_line}
  fi

  # total cores
  cpus_cores_line=$(echo $line | grep -Eo 'cpus_cores:[ ]*[0-9]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')

  if [ -n "$cpus_cores_line" ]; then
    cpus_cores=${cpus_cores_line}
  fi

  # Exp
  if echo "$line" | grep -q 'Exp:'; then
      exp=$(echo "$line" | grep -Eo 'Exp:[ ]*[a-zA-Z0-9_.-]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
  else
      exp=null
  fi

  # FOM version
  if echo "$line" | grep -q 'FOM_version:'; then
      echo $line
      fom_version=$(echo "$line" | grep -Eo 'FOM_version:[ ]*[a-zA-Z0-9_.-]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
  else
      fom_version=null
  fi

  # Description
  if echo "$line" | grep -q 'Description:'; then
      discription=$(echo "$line" | grep -Eo 'Description:[ ]*[a-zA-Z0-9_.-]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
  else
      discription=null
  fi

  # --- JSON ---
  cat <<EOF > results/result${i}.json
{
  "code": "$code",
  "system": "$system",
  "FOM": "$fom",
  "FOM_version": "$fom_version",
  "Exp": "$exp",
  "cpu_name": "$cpu_name",
  "gpu_name": "$gpu_name",
  "node_count": "$node_count",
  "cpus_per_node": "$cpus_per_node",
  "gpus_per_node": "$gpus_per_node",
  "node_count": "$node_count",
  "uname": "$uname_info",
  "cpu_cores": "$cpu_cores",
  "discription": "$discription"
}
EOF

  echo "results/result${i}.json created."

  # error at a64fx
  #  "gcc_version": "$gcc_version",

  i=$(expr $i + 1)

done < results/result
