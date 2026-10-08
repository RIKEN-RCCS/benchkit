#!/bin/bash
# Emit records on hosts without a JSON runtime. Parsing belongs to the consumer.

bk_json_quote() {
  local value="$1" char escaped code
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  for ((code = 1; code < 32; code++)); do
    printf -v escaped '\\u%04x' "$code"
    printf -v char '\\%03o' "$code"
    printf -v char '%b' "$char"
    value=${value//"$char"/"$escaped"}
  done
  printf '"%s"' "$value"
}

bk_json_object() {
  local separator="" kind key value
  [ $(( $# % 3 )) -eq 0 ] || return 2
  printf '{'
  while [ "$#" -gt 0 ]; do
    kind="$1" key="$2" value="$3"
    shift 3
    printf '%s' "$separator"
    bk_json_quote "$key"
    printf ':'
    case "$kind" in
      string) bk_json_quote "$value" ;;
      # Only JSON produced by this writer or fixed literals, never external input.
      json) printf '%s' "$value" ;;
      *) return 2 ;;
    esac
    separator=,
  done
  printf '}\n'
}

bk_json_lines_array() {
  local line separator=""
  printf '['
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    printf '%s' "$separator"
    bk_json_quote "$line"
    separator=,
  done
  printf ']\n'
}
