#!/usr/bin/env bash
set -euo pipefail

runner_version="v18.5.0"
go_version="1.25.0"
arch=""
site=""
gitlab_url=""
login_token=""
jacamar_token=""
login_tag=""
jacamar_tag=""
scheduler="pbs"
jacamar_repo=""
base_dir=""
service_host=""
allow_user="${USER:-}"
command_delay="30s"
install_systemd=1
start_service=1
libseccomp_mode="auto"
jacamar_pbs_tools=""
jacamar_make_jobs="${JACAMAR_BUILD_MAKE_JOBS:-1}"
jacamar_gomaxprocs="${JACAMAR_BUILD_GOMAXPROCS:-1}"
jacamar_goflags="${JACAMAR_BUILD_GOFLAGS:--p=1 -gcflags=all=-dwarf=false}"
unrestricted_cmd_line=false
runner_proxy=""
runner_no_proxy=""

usage() {
  cat <<'EOF'
Usage:
  setup_runner.sh --site SITE --gitlab-url URL --login-token TOKEN --jacamar-token TOKEN [options]

Required:
  --site SITE              Site prefix used for tags if tags are omitted.
  --gitlab-url URL         GitLab URL shared by both runners.
  --login-token TOKEN      Runner token for the login/frontend runner.
  --jacamar-token TOKEN    Runner token for the Jacamar/batch runner.

Options:
  --arch amd64|arm64       Target architecture. Default: auto-detect.
  --login-tag TAG          Expected login runner tag for display only.
                           With runner authentication tokens, tags are set on GitLab.
  --jacamar-tag TAG        Expected Jacamar runner tag for display only.
                           With runner authentication tokens, tags are set on GitLab.
  --scheduler pbs|slurm|pjm
  --jacamar-repo URL       Jacamar-CI repository. Default: PJM fork for
                           --scheduler pjm, upstream otherwise.
  --base-dir DIR           Default: $HOME/gitlab-runner_jacamar-ci_{amd,arm}
  --service-host HOST      Default: hostname -s.
  --allow-user USER        Jacamar user_allowlist entry. Default: $USER.
  --runner-version VER     Default: v18.5.0.
  --go-version VER         Default: 1.25.0.
  --command-delay VALUE    Jacamar batch command_delay. Default: 30s.
  --jacamar-pbs-tools PATH Copy PATH to jacamar-ci/internal/executors/pbs/tools.go before build.
  --unrestricted-cmd-line Allow Jacamar to keep runner generated Git/token commands
                           on the command line. Useful when GIT_ASKPASS fails.
  --proxy URL              Set http_proxy/https_proxy in both the runner
                           config.toml environment and systemd user service.
                           If URL has no scheme, http:// is prepended.
  --no-proxy LIST          Set no_proxy/NO_PROXY in both the runner
                           config.toml environment and systemd user service.
  --libseccomp auto|system|local|none
                           Default: auto. Use system libseccomp if available,
                           build local gperf/libseccomp if missing.
  --with-libseccomp        Alias for --libseccomp local.
  --without-libseccomp     Alias for --libseccomp none.
  --no-systemd             Do not create a systemd user service.
  --no-start               Create and enable service, but do not start it.
  -h, --help               Show this help.

Environment overrides:
  JACAMAR_BUILD_MAKE_JOBS  Jacamar build make parallelism. Default: 1.
  JACAMAR_BUILD_GOMAXPROCS Jacamar build Go scheduler threads. Default: 1.
  JACAMAR_BUILD_GOFLAGS    Jacamar build Go flags.
                           Default: -p=1 -gcflags=all=-dwarf=false.

Example:
  curl -fsSL https://raw.githubusercontent.com/RIKEN-RCCS/benchkit/main/scripts/site/setup_runner.sh \
    | bash -s -- --arch amd64 --site genkai \
        --gitlab-url https://gitlab.example.jp \
        --login-token "$LOGIN_TOKEN" --jacamar-token "$JACAMAR_TOKEN" \
        --scheduler pjm --service-host genkai0001
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

info() {
  echo "[setup-site-runner] $*"
}

systemd_env_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value"
}

toml_string_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value"
}

write_systemd_env() {
  local unit_path="$1"
  local name="$2"
  local value="$3"
  [[ -n "$value" ]] || return 0
  printf 'Environment="%s=%s"\n' "$name" "$(systemd_env_escape "$value")" >> "$unit_path"
}

append_runner_env() {
  local name="$1"
  local value="$2"
  [[ -n "$value" ]] || return 0
  runner_env_entries+=", \"${name}=$(toml_string_escape "$value")\""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch) arch="${2:-}"; shift 2 ;;
    --site) site="${2:-}"; shift 2 ;;
    --gitlab-url) gitlab_url="${2:-}"; shift 2 ;;
    --login-token) login_token="${2:-}"; shift 2 ;;
    --jacamar-token) jacamar_token="${2:-}"; shift 2 ;;
    --login-tag) login_tag="${2:-}"; shift 2 ;;
    --jacamar-tag) jacamar_tag="${2:-}"; shift 2 ;;
    --scheduler) scheduler="${2:-}"; shift 2 ;;
    --jacamar-repo) jacamar_repo="${2:-}"; shift 2 ;;
    --base-dir) base_dir="${2:-}"; shift 2 ;;
    --service-host) service_host="${2:-}"; shift 2 ;;
    --allow-user) allow_user="${2:-}"; shift 2 ;;
    --runner-version) runner_version="${2:-}"; shift 2 ;;
    --go-version) go_version="${2:-}"; shift 2 ;;
    --command-delay) command_delay="${2:-}"; shift 2 ;;
    --jacamar-pbs-tools) jacamar_pbs_tools="${2:-}"; shift 2 ;;
    --unrestricted-cmd-line) unrestricted_cmd_line=true; shift ;;
    --proxy) runner_proxy="${2:-}"; shift 2 ;;
    --no-proxy) runner_no_proxy="${2:-}"; shift 2 ;;
    --libseccomp) libseccomp_mode="${2:-}"; shift 2 ;;
    --with-libseccomp) libseccomp_mode="local"; shift ;;
    --without-libseccomp) libseccomp_mode="none"; shift ;;
    --no-systemd) install_systemd=0; shift ;;
    --no-start) start_service=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$site" ]] || die "--site is required"
[[ -n "$gitlab_url" ]] || die "--gitlab-url is required"
[[ -n "$login_token" ]] || die "--login-token is required"
[[ -n "$jacamar_token" ]] || die "--jacamar-token is required"
[[ -n "$allow_user" ]] || die "--allow-user is required when USER is empty"

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

case "$libseccomp_mode" in
  auto|system|local|none) ;;
  *) die "--libseccomp must be auto, system, local, or none" ;;
esac

if [[ -n "$runner_proxy" ]]; then
  case "$runner_proxy" in
    http://*|https://*) ;;
    *) runner_proxy="http://${runner_proxy}" ;;
  esac
fi

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
base_dir="$(mkdir -p "$base_dir" && cd "$base_dir" && pwd)"

if [[ -z "$service_host" ]]; then
  service_host="$(hostname -s)"
fi

login_tag="${login_tag:-${site}_login}"
jacamar_tag="${jacamar_tag:-${site}_jacamar}"
login_desc="${site}-login"
jacamar_desc="${site}-jacamar"

for cmd in curl git tar make gcc g++; do
  command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
done

mkdir -p "$base_dir/bin" "$base_dir/builds" "$base_dir/cache"

runner_bin="${base_dir}/bin/gitlab-runner"
jacamar_bin="${base_dir}/bin/jacamar"
runner_url="https://gitlab-runner-downloads.s3.amazonaws.com/${runner_version}/binaries/gitlab-runner-linux-${runner_arch}"

if [[ ! -x "$runner_bin" ]]; then
  info "Downloading GitLab Runner ${runner_version} (${runner_arch})"
  curl -fsSL "$runner_url" -o "$runner_bin"
  chmod +x "$runner_bin"
else
  info "GitLab Runner already exists: $runner_bin"
fi

work_dir="${base_dir}/_bootstrap"
rm -rf "$work_dir"
mkdir -p "$work_dir"

install_go() {
  local go_pkg="go${go_version}.linux-${go_arch}.tar.gz"
  info "Installing Go ${go_version} (${go_arch})"
  curl -fsSL "https://go.dev/dl/${go_pkg}" -o "${work_dir}/${go_pkg}"
  tar -C "$work_dir" -xzf "${work_dir}/${go_pkg}"
  export GOROOT="${work_dir}/go"
  export GOBIN="${GOROOT}/bin"
  export PATH="${GOBIN}:${PATH}"
}

build_local_libseccomp() {
  local gperf_ver="3.1"
  local sec_ver="2.5.5"
  local local_prefix="${work_dir}/local"
  local gperf_prefix="${local_prefix}/gperf"
  local sec_prefix="${local_prefix}/libseccomp"

  info "Building local gperf/libseccomp"
  curl -fsSL "https://ftp.gnu.org/gnu/gperf/gperf-${gperf_ver}.tar.gz" -o "${work_dir}/gperf.tar.gz"
  tar -C "$work_dir" -xzf "${work_dir}/gperf.tar.gz"
  (cd "${work_dir}/gperf-${gperf_ver}" && ./configure --prefix="$gperf_prefix" && make -j"$(nproc)" && make install)
  export PATH="${gperf_prefix}/bin:${PATH}"

  curl -fsSL "https://github.com/seccomp/libseccomp/releases/download/v${sec_ver}/libseccomp-${sec_ver}.tar.gz" -o "${work_dir}/libseccomp.tar.gz"
  tar -C "$work_dir" -xzf "${work_dir}/libseccomp.tar.gz"
  (cd "${work_dir}/libseccomp-${sec_ver}" && ./configure --prefix="$sec_prefix" --disable-shared && make -j"$(nproc)" && make install)
  export PKG_CONFIG_PATH="${sec_prefix}/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
  export LD_LIBRARY_PATH="${sec_prefix}/lib:${LD_LIBRARY_PATH:-}"
  export LIBRARY_PATH="${sec_prefix}/lib:${LIBRARY_PATH:-}"
  export CPATH="${sec_prefix}/include:${CPATH:-}"
}

have_system_libseccomp() {
  if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libseccomp; then
    return 0
  fi

  local test_c="${work_dir}/check-libseccomp.c"
  local test_bin="${work_dir}/check-libseccomp"
  cat > "$test_c" <<'EOF'
#include <seccomp.h>
int main(void) {
  return seccomp_api_get() < 0;
}
EOF
  gcc "$test_c" -lseccomp -o "$test_bin" >/dev/null 2>&1
}

configure_libseccomp() {
  case "$libseccomp_mode" in
    none)
      info "Skipping libseccomp detection/build (--libseccomp none)"
      ;;
    system)
      if have_system_libseccomp; then
        info "Using system libseccomp"
      else
        die "System libseccomp was requested but not found"
      fi
      ;;
    local)
      build_local_libseccomp
      ;;
    auto)
      if have_system_libseccomp; then
        info "Using system libseccomp"
      else
        info "System libseccomp not found; building local copy"
        build_local_libseccomp
      fi
      ;;
  esac
}

if [[ ! -x "$jacamar_bin" ]]; then
  install_go
  configure_libseccomp

  info "Building Jacamar-CI from ${jacamar_repo}"
  git clone "$jacamar_repo" "${work_dir}/jacamar-ci"
  if [[ -n "$jacamar_pbs_tools" ]]; then
    [[ -f "$jacamar_pbs_tools" ]] || die "--jacamar-pbs-tools file not found: $jacamar_pbs_tools"
    cp "$jacamar_pbs_tools" "${work_dir}/jacamar-ci/internal/executors/pbs/tools.go"
  fi
  (
    cd "${work_dir}/jacamar-ci"
    export CC=gcc CXX=g++ CGO_ENABLED=1
    export GOMAXPROCS="${GOMAXPROCS:-$jacamar_gomaxprocs}"
    export GOFLAGS="${GOFLAGS:-$jacamar_goflags}"
    info "Using Jacamar build limits: make -j${jacamar_make_jobs}, GOMAXPROCS=${GOMAXPROCS}, GOFLAGS=${GOFLAGS}"
    make -j"$jacamar_make_jobs" build
    make install PREFIX="$base_dir"
  )
else
  info "Jacamar already exists: $jacamar_bin"
fi

rm -rf "$work_dir"

info "Writing custom executor helper scripts"
cat > "${base_dir}/config.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${base_dir}"
BASE_BUILD_DIR="\${BASE_DIR}/builds"
BASE_CACHE_DIR="\${BASE_DIR}/cache"

SLUG="\${CUSTOM_ENV_CI_PROJECT_PATH_SLUG:-unknown}"
JOB_ID="\${CUSTOM_ENV_CI_JOB_ID:-\$\$}"

UNIQUE_BUILD_DIR="\${BASE_BUILD_DIR}/\${SLUG}/job_\${JOB_ID}"
UNIQUE_CACHE_DIR="\${BASE_CACHE_DIR}/\${SLUG}/job_\${JOB_ID}"

cat <<EOS
{
  "builds_dir": "\${UNIQUE_BUILD_DIR}",
  "cache_dir": "\${UNIQUE_CACHE_DIR}",
  "builds_dir_is_shared": false,
  "shell": "bash",
  "hostname": "runner-\${JOB_ID}",
  "driver": {
    "name": "custom-runner",
    "version": "v1.0"
  },
  "job_env": {
    "CUSTOM_RUNNER_JOB_ID": "\${JOB_ID}",
    "CUSTOM_RUNNER_PROJECT_SLUG": "\${SLUG}",
    "CUSTOM_UNIQUE_BUILD_DIR": "\${UNIQUE_BUILD_DIR}",
    "CUSTOM_UNIQUE_CACHE_DIR": "\${UNIQUE_CACHE_DIR}",
    "CUSTOM_DIR": "\${BASE_DIR}"
  }
}
EOS
EOF

cat > "${base_dir}/prepare.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 0
EOF

cat > "${base_dir}/runner-env.sh" <<'EOF'
#!/usr/bin/env bash

source_if_readable() {
  local file="$1"
  if [[ -r "$file" ]]; then
    # shellcheck disable=SC1090
    source "$file" || true
  fi
}

source_if_readable /etc/profile
source_if_readable /etc/bashrc

if ! type module >/dev/null 2>&1; then
  source_if_readable /etc/profile.d/modules.sh
  source_if_readable /etc/profile.d/z00_lmod.sh
fi

source_if_readable "${HOME}/.bashrc"

unset -f source_if_readable
EOF

cat > "${base_dir}/run.sh" <<EOF
#!/usr/bin/env bash
RUNNER_ENV="\${CUSTOM_DIR:-${base_dir}}/runner-env.sh"
if [[ -r "\${RUNNER_ENV}" ]]; then
  source "\${RUNNER_ENV}"
elif [[ -r "\${HOME}/.bashrc" ]]; then
  source "\${HOME}/.bashrc"
fi
set -eo pipefail
exec "\$@"
EOF

cat > "${base_dir}/cleanup.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${base_dir}"
LOGFILE="\${CUSTOM_DIR:-\${BASE_DIR}}/custom_cleanup.log"
echo "CLEANUP STARTED at \$(date)" >> "\$LOGFILE"

BUILD_DIR="\${CUSTOM_UNIQUE_BUILD_DIR:-}"
CACHE_DIR="\${CUSTOM_UNIQUE_CACHE_DIR:-}"

case "\$BUILD_DIR" in
  "\${BASE_DIR}/builds/"*) [[ -d "\$BUILD_DIR" ]] && rm -rf -- "\$BUILD_DIR" ;;
esac

case "\$CACHE_DIR" in
  "\${BASE_DIR}/cache/"*) [[ -d "\$CACHE_DIR" ]] && rm -rf -- "\$CACHE_DIR" ;;
esac

echo "CLEANUP DONE at \$(date)" >> "\$LOGFILE"
EOF

chmod +x "${base_dir}/config.sh" "${base_dir}/prepare.sh" "${base_dir}/runner-env.sh" "${base_dir}/run.sh" "${base_dir}/cleanup.sh"

info "Writing Jacamar config"
cat > "${base_dir}/custom-config.toml" <<EOF
[general]
executor = "${scheduler}"
data_dir = "${base_dir}"
retain_logs = true
unrestricted_cmd_line = ${unrestricted_cmd_line}

[auth]
downscope = "setuid"
user_allowlist = ["${allow_user}"]

[batch]
command_delay = "${command_delay}"
EOF

runner_path_env="PATH=${base_dir}/bin:/usr/local/bin:/usr/bin:/bin"
runner_env_entries="\"$(toml_string_escape "$runner_path_env")\""
if [[ -n "$runner_proxy" ]]; then
  append_runner_env "http_proxy" "$runner_proxy"
  append_runner_env "https_proxy" "$runner_proxy"
  append_runner_env "HTTP_PROXY" "$runner_proxy"
  append_runner_env "HTTPS_PROXY" "$runner_proxy"
fi
if [[ -n "$runner_no_proxy" ]]; then
  append_runner_env "no_proxy" "$runner_no_proxy"
  append_runner_env "NO_PROXY" "$runner_no_proxy"
fi
login_template="${base_dir}/login-runner.template.toml"
jacamar_template="${base_dir}/jacamar-runner.template.toml"

cat > "$login_template" <<EOF
[[runners]]
  shell = "bash"
  environment = [${runner_env_entries}]
  [runners.custom]
    config_exec = "${base_dir}/config.sh"
    prepare_exec = "${base_dir}/prepare.sh"
    run_exec = "${base_dir}/run.sh"
    cleanup_exec = "${base_dir}/cleanup.sh"
EOF

cat > "$jacamar_template" <<EOF
[[runners]]
  shell = "bash"
  environment = [${runner_env_entries}]
  [runners.custom]
    config_exec = "${jacamar_bin}"
    config_args = ["--no-auth", "config", "--configuration", "${base_dir}/custom-config.toml"]
    prepare_exec = "${jacamar_bin}"
    prepare_args = ["--no-auth", "prepare"]
    run_exec = "${jacamar_bin}"
    run_args = ["--no-auth", "run"]
    cleanup_exec = "${jacamar_bin}"
    cleanup_args = ["--no-auth", "cleanup", "--configuration", "${base_dir}/custom-config.toml"]
EOF

register_runner() {
  local desc="$1"
  local token="$2"
  local template="$3"

  info "Registering runner: ${desc}"
  "$runner_bin" register \
    --non-interactive \
    --url "$gitlab_url" \
    --token "$token" \
    --executor "custom" \
    --description "$desc" \
    --builds-dir "${base_dir}/builds" \
    --cache-dir "${base_dir}/cache" \
    --config "${base_dir}/config.toml" \
    --template-config "$template"
}

register_runner "$login_desc" "$login_token" "$login_template"
register_runner "$jacamar_desc" "$jacamar_token" "$jacamar_template"

if [[ "$install_systemd" -eq 1 ]]; then
  service_name="gitlab-runner-${site}-${arch_suffix}.service"
  unit_dir="${HOME}/.config/systemd/user"
  unit_path="${unit_dir}/${service_name}"
  mkdir -p "$unit_dir"

  info "Writing systemd user service: ${unit_path}"
  cat > "$unit_path" <<EOF
[Unit]
Description=GitLab Runner service for ${site} (${arch})
After=network.target
ConditionHost=${service_host}

[Service]
EOF
  if [[ -n "$runner_proxy" ]]; then
    write_systemd_env "$unit_path" "http_proxy" "$runner_proxy"
    write_systemd_env "$unit_path" "https_proxy" "$runner_proxy"
    write_systemd_env "$unit_path" "HTTP_PROXY" "$runner_proxy"
    write_systemd_env "$unit_path" "HTTPS_PROXY" "$runner_proxy"
  fi
  if [[ -n "$runner_no_proxy" ]]; then
    write_systemd_env "$unit_path" "no_proxy" "$runner_no_proxy"
    write_systemd_env "$unit_path" "NO_PROXY" "$runner_no_proxy"
  fi
  cat >> "$unit_path" <<EOF
ExecStart=${runner_bin} run --config ${base_dir}/config.toml --working-directory ${HOME}
Restart=always
RestartSec=10
StandardOutput=append:${base_dir}/gitlab-runner.log
StandardError=append:${base_dir}/gitlab-runner.err

[Install]
WantedBy=default.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable "$service_name"
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$allow_user" || true
  fi
  if [[ "$start_service" -eq 1 ]]; then
    systemctl --user restart "$service_name"
    systemctl --user --no-pager status "$service_name" || true
  fi
fi

info "Done"
info "Base dir: ${base_dir}"
info "Login tag: ${login_tag}"
info "Jacamar tag: ${jacamar_tag}"
info "Jacamar unrestricted_cmd_line: ${unrestricted_cmd_line}"
if [[ -n "$runner_proxy" ]]; then
  info "Runner proxy: ${runner_proxy} (config.toml environment + systemd service)"
fi
if [[ -n "$runner_no_proxy" ]]; then
  info "Runner no_proxy: ${runner_no_proxy} (config.toml environment + systemd service)"
fi
