#!/bin/bash
# Split compiler command strings without evaluating shell syntax.
bk_snapshot_compiler_words() {
  local value=$1 char quote='' word='' escaped=false i
  BK_SNAPSHOT_COMPILER_WORDS=()
  for ((i=0; i<${#value}; i++)); do
    char=${value:i:1}
    if $escaped; then word+=$char; escaped=false; continue; fi
    if [[ $quote == "'" ]]; then
      if [[ $char == "'" ]]; then quote=''; else word+=$char; fi
    elif [[ $char == '\' ]]; then escaped=true
    elif [[ $quote == '"' ]]; then
      if [[ $char == '"' ]]; then quote=''; else word+=$char; fi
    elif [[ $char == "'" || $char == '"' ]]; then quote=$char
    elif [[ $char == ' ' || $char == $'\t' ]]; then
      if [[ -n $word ]]; then BK_SNAPSHOT_COMPILER_WORDS+=("$word"); word=''; fi
    elif [[ $char == ';' || $char == '|' || $char == '&' || $char == '<' || $char == '>' || $char == $'\n' ]]; then
      return 1
    else word+=$char
    fi
  done
  [[ -z $quote && $escaped == false ]] || return 1
  [[ -z $word ]] || BK_SNAPSHOT_COMPILER_WORDS+=("$word")
}

bk_snapshot_command_names() {
  local defaults='bash sh cc CC ftn c++ gcc g++ clang clang++ flang flang-new amdclang amdclang++ amdflang icc icpc ifort icx icpx ifx fcc fccpx frt frtpx mpicc mpicxx mpic++ mpiclang mpiclang++ mpifcc mpifccpx mpifrt mpifrtpx mpif90 mpifort mpiicc mpiicpc mpiifort mpiicx mpiicpx mpiifx gfortran nvcc nvc nvc++ nvfortran cmake make ninja ld ar pkg-config python3 apptainer singularity ncu nsys'
  local name cmd
  local -a BK_SNAPSHOT_COMPILER_WORDS
  # The legacy override is whitespace separated; compiler variables also
  # support quoted paths and flags. Neither source is evaluated.
  for cmd in ${BK_SNAPSHOT_TOOL_COMMANDS:-$defaults}; do printf '%s\n' "$cmd"; done
  for name in CC CXX FC F77 F90 OMPI_CC OMPI_CXX OMPI_FC MPICH_CC MPICH_CXX MPICH_FC; do
    [[ -n ${!name:-} ]] || continue
    bk_snapshot_compiler_words "${!name}" || continue
    for cmd in "${BK_SNAPSHOT_COMPILER_WORDS[@]}"; do
      [[ $cmd != -* ]] || break
      [[ $cmd != *'$'* && $cmd != *'`'* ]] || break
      [[ $cmd == *=* ]] && continue
      printf '%s\n' "$cmd"
      case ${cmd##*/} in ccache|sccache|distcc|env) ;; *) break ;; esac
    done
  done
}
