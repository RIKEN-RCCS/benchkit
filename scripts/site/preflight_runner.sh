#!/usr/bin/env bash
set -euo pipefail

site=""
arch=""
gitlab_url=""
runner_version="v18.5.0"
go_version="1.25.0"
scheduler="pbs"
jacamar_repo=""
base_dir=""
service_host=""
explicit_proxy=""
connect_timeout=5
max_time=12

usage() {
  cat <<'EOF'
Usage:
  preflight_runner.sh --gitlab-url URL [options]

Options:
  --site SITE              Site prefix used for runner service lookup.
  --arch amd64|arm64       Target architecture. Default: auto-detect.
  --gitlab-url URL         CI GitLab URL to test in addition to gitlab.com/github.com.
  --runner-version VER     GitLab Runner version used by setup_runner.sh. Default: v18.5.0.
  --go-version VER         Go version used by setup_runner.sh. Default: 1.25.0.
  --scheduler pbs|slurm|pjm
                           Scheduler used to infer the default Jacamar-CI repository.
  --jacamar-repo URL       Jacamar-CI repository. Default: PJM fork for
                           --scheduler pjm, upstream otherwise.
  --base-dir DIR           Default: $HOME/gitlab-runner_jacamar-ci_{amd,arm}
  --service-host HOST      Default: hostname -s.
  --proxy URL              Add an explicit proxy candidate to test.
                           If URL has no scheme, http:// is prepended.
  --connect-timeout SEC    curl connect timeout. Default: 5.
  --max-time SEC           curl total timeout. Default: 12.
  -h, --help               Show this help.

This script performs only login-node checks. It does not submit scheduler jobs.
It discovers proxy candidates from the current environment, shell profiles,
system profiles, existing runner systemd units, and runner config.toml files.
EOF
}

info() {
  echo "[preflight] $*"
}

ok() {
  echo "[OK] $*"
}

warn() {
  echo "[WARN] $*"
}

ng() {
  echo "[NG] $*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

normalize_url() {
  local value="$1"
  case "$value" in
    http://*|https://*) printf '%s' "$value" ;;
    *) printf 'https://%s' "$value" ;;
  esac
}

normalize_proxy() {
  local value="$1"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  value="${value%,}"
  value="${value%;}"
  [[ -n "$value" ]] || return 0
  case "$value" in
    http://*|https://*) printf '%s' "$value" ;;
    *) printf 'http://%s' "$value" ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site) site="${2:-}"; shift 2 ;;
    --arch) arch="${2:-}"; shift 2 ;;
    --gitlab-url) gitlab_url="${2:-}"; shift 2 ;;
    --runner-version) runner_version="${2:-}"; shift 2 ;;
    --go-version) go_version="${2:-}"; shift 2 ;;
    --scheduler) scheduler="${2:-}"; shift 2 ;;
    --jacamar-repo) jacamar_repo="${2:-}"; shift 2 ;;
    --base-dir) base_dir="${2:-}"; shift 2 ;;
    --service-host) service_host="${2:-}"; shift 2 ;;
    --proxy) explicit_proxy="${2:-}"; shift 2 ;;
    --connect-timeout) connect_timeout="${2:-}"; shift 2 ;;
    --max-time) max_time="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$gitlab_url" ]] || die "--gitlab-url is required"
gitlab_url="$(normalize_url "$gitlab_url")"

if [[ -z "$arch" ]]; then
  case "$(uname -m)" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) die "Cannot auto-detect arch from uname -m=$(uname -m); pass --arch" ;;
  esac
fi

case "$arch" in
  amd64) arch_suffix="amd"; runner_arch="amd64"; go_arch="amd64" ;;
  arm64) arch_suffix="arm"; runner_arch="arm64"; go_arch="arm64" ;;
  *) die "--arch must be amd64 or arm64" ;;
esac

case "$scheduler" in
  pbs|slurm|pjm) ;;
  *) die "--scheduler must be pbs, slurm, or pjm" ;;
esac

if [[ -z "$jacamar_repo" ]]; then
  if [[ "$scheduler" == "pjm" ]]; then
    jacamar_repo="https://gitlab.com/yoshifuminakamura/jacamar-ci.git"
  else
    jacamar_repo="https://gitlab.com/ecp-ci/jacamar-ci.git"
  fi
fi

if [[ -z "$base_dir" ]]; then
  base_dir="${HOME}/gitlab-runner_jacamar-ci_${arch_suffix}"
fi

if [[ -z "$service_host" ]]; then
  service_host="$(hostname -s 2>/dev/null || hostname)"
fi

declare -a proxy_candidates=()
declare -A seen_proxy=()
declare -A proxy_sources=()

add_proxy_candidate() {
  local raw="$1"
  local source="$2"
  local proxy
  proxy="$(normalize_proxy "$raw")"
  [[ -n "$proxy" ]] || return 0
  case "$proxy" in
    http://*|https://*) ;;
    *) return 0 ;;
  esac
  if [[ -z "${seen_proxy[$proxy]+_}" ]]; then
    proxy_candidates+=("$proxy")
    seen_proxy[$proxy]=1
    proxy_sources[$proxy]="$source"
  else
    proxy_sources[$proxy]="${proxy_sources[$proxy]}, $source"
  fi
}

collect_proxy_from_env() {
  local name value
  for name in http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; do
    value="${!name:-}"
    [[ -n "$value" ]] && add_proxy_candidate "$value" "env:$name"
  done
  return 0
}

collect_proxy_from_file() {
  local file="$1"
  [[ -r "$file" ]] || return 0
  local line url
  while IFS= read -r line; do
    [[ "$line" =~ [Pp][Rr][Oo][Xx][Yy] ]] || continue
    while IFS= read -r url; do
      add_proxy_candidate "$url" "$file"
    done < <(printf '%s\n' "$line" | grep -Eo 'https?://[^[:space:]"'\'',;<>]+' || true)
  done < "$file"
  return 0
}

collect_proxy_candidates() {
  collect_proxy_from_env

  if [[ -n "$explicit_proxy" ]]; then
    add_proxy_candidate "$explicit_proxy" "argument:--proxy"
  fi

  local files=(
    "${HOME}/.bashrc"
    "${HOME}/.bash_profile"
    "${HOME}/.profile"
    "${HOME}/.zshrc"
    "/etc/profile"
    "/etc/environment"
  )

  shopt -s nullglob
  files+=(/etc/profile.d/*.sh)
  files+=("${HOME}/.config/systemd/user"/gitlab-runner-*.service)
  files+=("${base_dir}/config.toml")
  files+=("${HOME}"/gitlab-runner_jacamar-ci_*/config.toml)
  shopt -u nullglob

  local file
  for file in "${files[@]}"; do
    collect_proxy_from_file "$file"
  done
  return 0
}

curl_probe() {
  local url="$1"
  local proxy="${2:-}"
  local output status
  if [[ -n "$proxy" ]]; then
    output=$(env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY \
      curl -I -L -sS -o /dev/null -w '%{http_code}' \
        --connect-timeout "$connect_timeout" --max-time "$max_time" \
        -x "$proxy" "$url" 2>&1) || {
      printf 'FAIL %s' "$output"
      return 1
    }
  else
    output=$(env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY \
      curl -I -L -sS -o /dev/null -w '%{http_code}' \
        --connect-timeout "$connect_timeout" --max-time "$max_time" \
        "$url" 2>&1) || {
      printf 'FAIL %s' "$output"
      return 1
    }
  fi

  status="$output"
  case "$status" in
    2*|3*) printf 'HTTP %s' "$status"; return 0 ;;
    *) printf 'HTTP %s' "$status"; return 1 ;;
  esac
}

check_commands() {
  info "Checking local tool availability"
  local cmd
  for cmd in curl git tar make gcc g++ systemctl loginctl; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ok "command found: $cmd ($(command -v "$cmd"))"
    else
      warn "command not found: $cmd"
    fi
  done
}

check_systemd_user() {
  info "Checking systemd user and linger"
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl not found"
  elif systemctl --user status >/dev/null 2>&1; then
    ok "systemctl --user is usable"
    systemctl --user is-system-running 2>/dev/null || true
    systemctl --user show-environment 2>/dev/null | grep -Ei '^(http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY|no_proxy|NO_PROXY)=' || true
  else
    ng "systemctl --user is not usable"
  fi

  if command -v loginctl >/dev/null 2>&1; then
    loginctl show-user "${USER:-}" -p Linger 2>/dev/null || warn "loginctl show-user failed"
  else
    warn "loginctl not found"
  fi

  if [[ -n "$site" ]]; then
    local service_name unit_path
    service_name="gitlab-runner-${site}-${arch_suffix}.service"
    unit_path="${HOME}/.config/systemd/user/${service_name}"
    if [[ -f "$unit_path" ]]; then
      ok "runner service file exists: $unit_path"
      systemctl --user show "$service_name" -p Environment 2>/dev/null || true
    else
      warn "runner service file not found yet: $unit_path"
    fi
  fi
}

check_runner_configs() {
  info "Checking runner config candidates"
  local config
  shopt -s nullglob
  for config in "${base_dir}/config.toml" "${HOME}"/gitlab-runner_jacamar-ci_*/config.toml; do
    [[ -r "$config" ]] || continue
    ok "runner config found: $config"
    grep -nA3 -B1 'environment = ' "$config" || true
  done
  shopt -u nullglob
}

print_proxy_candidates() {
  info "Discovered proxy candidates"
  if [[ "${#proxy_candidates[@]}" -eq 0 ]]; then
    warn "no proxy candidates found"
    return 0
  fi
  local proxy
  for proxy in "${proxy_candidates[@]}"; do
    echo "  - ${proxy}  (${proxy_sources[$proxy]})"
  done
}

test_connectivity() {
  local runner_url go_pkg go_url
  runner_url="https://gitlab-runner-downloads.s3.amazonaws.com/${runner_version}/binaries/gitlab-runner-linux-${runner_arch}"
  go_pkg="go${go_version}.linux-${go_arch}.tar.gz"
  go_url="https://go.dev/dl/${go_pkg}"
  local urls=(
    "https://gitlab.com"
    "https://github.com"
    "$gitlab_url"
    "$runner_url"
    "$go_url"
    "https://ftp.gnu.org/gnu/gperf/gperf-3.1.tar.gz"
    "https://github.com/seccomp/libseccomp/releases/download/v2.5.5/libseccomp-2.5.5.tar.gz"
  )
  case "$jacamar_repo" in
    http://*|https://*) urls+=("$jacamar_repo") ;;
    *) warn "skipping non-HTTP Jacamar repo connectivity check: ${jacamar_repo}" ;;
  esac
  declare -A seen_url=()
  declare -a unique_urls=()
  local url
  for url in "${urls[@]}"; do
    [[ -z "${seen_url[$url]+_}" ]] || continue
    seen_url[$url]=1
    unique_urls+=("$url")
  done

  info "Testing direct connectivity"
  local result direct_fail=0
  for url in "${unique_urls[@]}"; do
    if result="$(curl_probe "$url")"; then
      ok "direct ${url}: ${result}"
    else
      ng "direct ${url}: ${result}"
      direct_fail=1
    fi
  done

  declare -A proxy_ok_count=()
  local proxy best_proxy="" best_count=0 count
  if [[ "${#proxy_candidates[@]}" -gt 0 ]]; then
    info "Testing proxy candidates"
    for proxy in "${proxy_candidates[@]}"; do
      proxy_ok_count[$proxy]=0
      for url in "${unique_urls[@]}"; do
        if result="$(curl_probe "$url" "$proxy")"; then
          ok "proxy ${proxy} -> ${url}: ${result}"
          proxy_ok_count[$proxy]=$((proxy_ok_count[$proxy] + 1))
        else
          ng "proxy ${proxy} -> ${url}: ${result}"
        fi
      done
      count="${proxy_ok_count[$proxy]}"
      if (( count > best_count )); then
        best_count="$count"
        best_proxy="$proxy"
      fi
    done
  fi

  info "Summary"
  if [[ -n "$best_proxy" && "$best_count" -gt 0 ]]; then
    if (( best_count == ${#unique_urls[@]} )); then
      ok "recommended proxy covers all tested URLs: ${best_proxy}"
    else
      warn "best proxy covers ${best_count}/${#unique_urls[@]} URLs: ${best_proxy}"
    fi
    echo "Suggested setup option:"
    echo "  --proxy ${best_proxy}"
  elif [[ "$direct_fail" -eq 0 ]]; then
    ok "all tested URLs are reachable without proxy"
  else
    warn "no working proxy candidate found; inspect site proxy settings manually"
  fi
}

info "Site runner preflight"
echo "  site=${site:-<not specified>}"
echo "  arch=${arch}"
echo "  service_host=${service_host}"
echo "  base_dir=${base_dir}"
echo "  gitlab_url=${gitlab_url}"
echo

check_commands
echo
collect_proxy_candidates
print_proxy_candidates
echo
test_connectivity
echo
check_systemd_user
echo
check_runner_configs
echo
info "Done. No scheduler jobs were submitted."
