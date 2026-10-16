#!/bin/bash
set -euo pipefail
mode=makefile
if [[ "${1:-}" == --compile-log ]]; then mode=compile; shift; fi
expected=$1
shift
[[ -n "$expected" && $# -gt 0 ]] || exit 2
awk -v expected="$expected" -v mode="$mode" '
 function check(actual, n,a,i) {
  n=split(expected,a,/[[:space:]]+/)
  for(i=1;i<=n;i++) if(a[i]!="" && index(" "actual" "," "a[i]" ")==0) {
   print "Missing expected Fortran flag "a[i]": "actual > "/dev/stderr"; bad=1
  }
 }
 mode=="makefile" && /^FCFLAGS[[:space:]]*=/ {
  sub(/^[^=]*=[[:space:]]*/,""); check($0); checked++
 }
 mode=="compile" && /(^|\/)mpif(90|ort)[[:space:]]/ && /[[:space:]]-c[[:space:]]/ && /\.(f|f90)([[:space:]]|$)/ {
  check($0); checked++
 }
 END {
  if(!checked) {print "No Fortran "mode" records found" > "/dev/stderr"; exit 1}
  if(bad) exit 1
  print "Verified Fortran "mode" records: "checked
 }' "$@"
