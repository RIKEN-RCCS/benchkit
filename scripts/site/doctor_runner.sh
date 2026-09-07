#!/usr/bin/env bash
set -euo pipefail

site=""
arch=""
base_dir=""

usage() {
  cat <<'EOF'
Usage:
  doctor_runner.sh [options]

Options:
  --site SITE              Site prefix used for the systemd user service name.
  --arch amd64|arm64       Runner architecture. Default: auto-detect.
  --base-dir DIR           Default: $HOME/gitlab-runner_jacamar-ci_{amd,arm}
  -h, --help               Show this help.

This script inspects an installed Benchkit GitLab Runner/Jacamar setup on the
login node. It does not access GitLab, submit scheduler jobs, or print runner
tokens. Checks are limited to generated helper scripts, runner config markers,
systemd unit shape, and persistent build-cache readiness.
EOF
}

ok_count=0
warn_count=0
fail_count=0

ok() {
  ok_count=$((ok_count + 1))
  printf '[OK] %s\n' "$*"
}

warn() {
  warn_count=$((warn_count + 1))
  printf '[WARN] %s\n' "$*"
}

fail() {
  fail_count=$((fail_count + 1))
  printf '[FAIL] %s\n' "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site) site="${2:-}"; shift 2 ;;
    --arch) arch="${2:-}"; shift 2 ;;
    --base-dir) base_dir="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [[ -z "$arch" ]]; then
  case "$(uname -m 2>/dev/null || printf 'unknown')" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) die "Cannot auto-detect arch; pass --arch amd64 or --arch arm64" ;;
  esac
fi

case "$arch" in
  amd64) arch_suffix="amd" ;;
  arm64) arch_suffix="arm" ;;
  *) die "--arch must be amd64 or arm64" ;;
esac

if [[ -z "$base_dir" ]]; then
  base_dir="${HOME}/gitlab-runner_jacamar-ci_${arch_suffix}"
fi
if [[ -d "$base_dir" ]]; then
  base_dir="$(cd "$base_dir" && pwd)"
fi

has_text() {
  local file="$1"
  local needle="$2"
  [[ -r "$file" ]] && grep -Fq -- "$needle" "$file"
}

expect_text() {
  local file="$1"
  local needle="$2"
  local ok_message="$3"
  local fail_message="$4"
  if has_text "$file" "$needle"; then
    ok "$ok_message"
  else
    fail "$fail_message"
  fi
}

expect_regex() {
  local file="$1"
  local regex="$2"
  local ok_message="$3"
  local fail_message="$4"
  if [[ -r "$file" ]] && grep -Eq -- "$regex" "$file"; then
    ok "$ok_message"
  else
    fail "$fail_message"
  fi
}

require_readable() {
  local path="$1"
  local label="$2"
  if [[ -r "$path" ]]; then
    ok "$label is readable"
  else
    fail "$label is missing or not readable: $path"
  fi
}

require_executable() {
  local path="$1"
  local label="$2"
  if [[ -x "$path" ]]; then
    ok "$label is executable"
  else
    fail "$label is missing or not executable: $path"
  fi
}

check_path_layout() {
  if [[ -d "$base_dir" ]]; then
    ok "base directory exists: $base_dir"
  else
    fail "base directory is missing: $base_dir"
    return 0
  fi

  require_executable "$base_dir/bin/gitlab-runner" "gitlab-runner binary"
  require_executable "$base_dir/bin/jacamar" "jacamar binary"
  require_executable "$base_dir/config.sh" "custom config helper"
  require_executable "$base_dir/prepare.sh" "custom prepare helper"
  require_executable "$base_dir/run.sh" "custom run helper"
  require_executable "$base_dir/cleanup.sh" "custom cleanup helper"
  require_readable "$base_dir/runner-env.sh" "runner environment helper"
  require_readable "$base_dir/config.toml" "GitLab Runner config"
  require_readable "$base_dir/custom-config.toml" "Jacamar config"

  if [[ -d "$base_dir/builds" ]]; then
    ok "builds directory exists"
  else
    warn "builds directory is missing; setup_runner.sh normally creates it"
  fi
  if [[ -d "$base_dir/cache" ]]; then
    ok "per-job cache directory exists"
  else
    warn "per-job cache directory is missing; setup_runner.sh normally creates it"
  fi
  if [[ -d "$base_dir/build_cache" ]]; then
    if [[ -w "$base_dir/build_cache" ]]; then
      ok "persistent build_cache directory exists and is writable"
    else
      warn "persistent build_cache directory exists but is not writable"
    fi
  elif [[ -w "$base_dir" ]]; then
    ok "persistent build_cache directory can be created under base directory"
  else
    warn "persistent build_cache directory is absent and base directory is not writable"
  fi
}

check_config_helper() {
  local file="$base_dir/config.sh"
  [[ -r "$file" ]] || return 0

  expect_text "$file" '"cache_dir"' "config helper emits per-job cache_dir" \
    "config helper does not emit cache_dir"
  expect_text "$file" '"builds_dir_is_shared": false' \
    "config helper marks builds_dir as not shared" \
    "config helper should emit builds_dir_is_shared=false"
  expect_text "$file" "CUSTOM_UNIQUE_BUILD_DIR" \
    "config helper exports CUSTOM_UNIQUE_BUILD_DIR" \
    "config helper should export CUSTOM_UNIQUE_BUILD_DIR"
  expect_text "$file" "CUSTOM_UNIQUE_CACHE_DIR" \
    "config helper exports CUSTOM_UNIQUE_CACHE_DIR" \
    "config helper should export CUSTOM_UNIQUE_CACHE_DIR"
  expect_text "$file" "CUSTOM_RUNNER_PROJECT_SLUG" \
    "config helper exports CUSTOM_RUNNER_PROJECT_SLUG" \
    "config helper should export CUSTOM_RUNNER_PROJECT_SLUG"
  expect_text "$file" "CUSTOM_DIR" \
    "config helper exports CUSTOM_DIR for persistent build cache discovery" \
    "config helper should export CUSTOM_DIR so build cache can use a persistent base"
}

check_run_helper() {
  local file="$base_dir/run.sh"
  [[ -r "$file" ]] || return 0

  expect_text "$file" "runner-env.sh" "run helper loads runner-env.sh" \
    "run helper should load runner-env.sh before executing the job"
  expect_text "$file" 'exec "$@"' "run helper execs the job command" \
    "run helper should end by execing the job command"
}

check_cleanup_helper() {
  local file="$base_dir/cleanup.sh"
  [[ -r "$file" ]] || return 0

  expect_text "$file" "CUSTOM_UNIQUE_BUILD_DIR" \
    "cleanup helper uses CUSTOM_UNIQUE_BUILD_DIR" \
    "cleanup helper should remove only the per-job build directory"
  expect_text "$file" "CUSTOM_UNIQUE_CACHE_DIR" \
    "cleanup helper uses CUSTOM_UNIQUE_CACHE_DIR" \
    "cleanup helper should remove only the per-job cache directory"
  expect_text "$file" '/builds/' "cleanup helper constrains build cleanup to builds/" \
    "cleanup helper should guard build cleanup under the base builds directory"
  expect_text "$file" '/cache/' "cleanup helper constrains cache cleanup to cache/" \
    "cleanup helper should guard cache cleanup under the base cache directory"

  if has_text "$file" "build_cache"; then
    warn "cleanup helper mentions build_cache; confirm persistent build cache is not removed"
  else
    ok "cleanup helper does not mention persistent build_cache"
  fi
}

check_runner_env_helper() {
  local file="$base_dir/runner-env.sh"
  [[ -r "$file" ]] || return 0

  expect_text "$file" "module" "runner-env helper attempts module initialization" \
    "runner-env helper should initialize module support when available"
  expect_text "$file" ".bashrc" "runner-env helper loads user shell environment" \
    "runner-env helper should load the user shell environment"
}

check_runner_config() {
  local file="$base_dir/config.toml"
  [[ -r "$file" ]] || return 0

  expect_text "$file" 'executor = "custom"' "runner config uses custom executor" \
    "runner config should use the custom executor"
  expect_text "$file" "environment = [" "runner config has an environment block" \
    "runner config should set an environment block"
  if has_text "$file" "PATH=${base_dir}/bin:"; then
    ok "runner config PATH includes base bin directory"
  else
    warn "runner config PATH may not include the base bin directory"
  fi
  expect_text "$file" "config.sh" "runner config references login config helper" \
    "runner config should reference the login config helper"
  expect_text "$file" "run.sh" "runner config references login run helper" \
    "runner config should reference the login run helper"
  expect_text "$file" "cleanup.sh" "runner config references login cleanup helper" \
    "runner config should reference the login cleanup helper"
  expect_text "$file" "jacamar" "runner config references Jacamar for batch runner" \
    "runner config should reference Jacamar for the batch runner"
  expect_text "$file" "custom-config.toml" \
    "runner config passes custom-config.toml to Jacamar" \
    "runner config should pass custom-config.toml to Jacamar"
}

check_jacamar_config() {
  local file="$base_dir/custom-config.toml"
  [[ -r "$file" ]] || return 0

  expect_text "$file" "[general]" "Jacamar config has [general]" \
    "Jacamar config should have [general]"
  expect_regex "$file" 'executor[[:space:]]*=[[:space:]]*"(pbs|slurm|pjm)"' \
    "Jacamar config uses a standard Benchkit scheduler executor" \
    "Jacamar config executor should be pbs, slurm, or pjm"
  expect_text "$file" "retain_logs = true" "Jacamar config retains logs" \
    "Jacamar config should retain logs for job diagnosis"
  expect_text "$file" "[auth]" "Jacamar config has [auth]" \
    "Jacamar config should have [auth]"
  expect_text "$file" 'downscope = "setuid"' "Jacamar config uses setuid downscope" \
    "Jacamar config should set downscope to setuid"
  expect_text "$file" "user_allowlist" "Jacamar config has a user allowlist" \
    "Jacamar config should set a user allowlist"
  expect_text "$file" "[batch]" "Jacamar config has [batch]" \
    "Jacamar config should have [batch]"
  expect_text "$file" "command_delay" "Jacamar config sets command_delay" \
    "Jacamar config should set command_delay"

  if has_text "$file" "unrestricted_cmd_line = true"; then
    warn "Jacamar unrestricted_cmd_line is enabled; use only when command-line token exposure is acceptable"
  elif has_text "$file" "unrestricted_cmd_line = false"; then
    ok "Jacamar unrestricted_cmd_line is disabled"
  else
    warn "Jacamar unrestricted_cmd_line is not explicit"
  fi
}

check_systemd_unit() {
  if [[ -z "$site" ]]; then
    warn "systemd unit check skipped; pass --site to check the expected service file"
    return 0
  fi

  local unit_path="${HOME}/.config/systemd/user/gitlab-runner-${site}-${arch_suffix}.service"
  if [[ ! -r "$unit_path" ]]; then
    warn "systemd user service is missing or not readable: $unit_path"
    return 0
  fi

  ok "systemd user service is readable"
  expect_text "$unit_path" "ConditionHost=" \
    "systemd unit pins the expected host" \
    "systemd unit should set ConditionHost for site-local runner placement"
  expect_text "$unit_path" "${base_dir}/bin/gitlab-runner" \
    "systemd unit starts the configured gitlab-runner binary" \
    "systemd unit should start the gitlab-runner binary under base directory"
  expect_text "$unit_path" "${base_dir}/config.toml" \
    "systemd unit uses the configured runner config.toml" \
    "systemd unit should pass the runner config.toml under base directory"
}

printf '[doctor] Benchkit site runner setup\n'
printf '  arch=%s\n' "$arch"
printf '  base_dir=%s\n' "$base_dir"
if [[ -n "$site" ]]; then
  printf '  site=%s\n' "$site"
else
  printf '  site=<not specified>\n'
fi
printf '\n'

check_path_layout
check_config_helper
check_run_helper
check_cleanup_helper
check_runner_env_helper
check_runner_config
check_jacamar_config
check_systemd_unit

printf '\n'
printf '[doctor] Summary: %d ok, %d warning(s), %d failure(s)\n' \
  "$ok_count" "$warn_count" "$fail_count"

if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi
exit 0
