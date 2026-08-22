#!/usr/bin/env bash
set -euo pipefail

site=""
repo_dir=""
venv_dir=""
db_path=""
env_file=""
result_server_url=""
on_calendar="minutely"
service_host=""
mode="dry-run"
record_observations=1
start_service=1
use_lock=1
lock_ttl_seconds=300
schedule_lookback_minutes=5

usage() {
  cat <<'EOF'
Usage:
  setup_trigger_runner.sh --site SITE --result-server-url URL [options]

Options:
  --site SITE              Site suffix used for the systemd unit name.
  --repo-dir DIR           Benchkit checkout. Default: current directory.
  --venv DIR               Python venv. Default: $HOME/fugakunext/venv.
  --db PATH                cx_portal.sqlite3 path.
                           Default: $HOME/fugakunext/$SITE/cx_portal.sqlite3.
  --env-file PATH          systemd EnvironmentFile.
                           Default: $HOME/.config/fncx/$SITE.env.
  --result-server-url URL  RESULT_SERVER URL passed to triggered pipelines.
  --on-calendar EXPR       systemd timer calendar. Default: minutely.
  --service-host HOST      Add ConditionHost=HOST for shared home directories.
  --submit                 Submit due/changed triggers.
  --dry-run                Evaluate only. Default.
  --no-record-observations Do not persist repo_ref fingerprints.
  --no-lock                Do not use the SQLite runner lock.
  --lock-ttl-seconds SEC   SQLite runner lock TTL. Default: 300.
  --schedule-lookback-minutes MIN
                           Scheduled trigger lookback window. Default: 5.
  --no-start               Write units but do not enable/start the timer.
  -h, --help               Show this help.

The generated user timer evaluates Portal trigger definitions with
result_server.trigger_runner. Keep GitLab trigger tokens in the EnvironmentFile,
not in this repository.
EOF
}

info() {
  echo "[setup-trigger-runner] $*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site) site="${2:-}"; shift 2 ;;
    --repo-dir) repo_dir="${2:-}"; shift 2 ;;
    --venv) venv_dir="${2:-}"; shift 2 ;;
    --db) db_path="${2:-}"; shift 2 ;;
    --env-file) env_file="${2:-}"; shift 2 ;;
    --result-server-url) result_server_url="${2:-}"; shift 2 ;;
    --on-calendar) on_calendar="${2:-}"; shift 2 ;;
    --service-host) service_host="${2:-}"; shift 2 ;;
    --submit) mode="submit"; shift ;;
    --dry-run) mode="dry-run"; shift ;;
    --no-record-observations) record_observations=0; shift ;;
    --no-lock) use_lock=0; shift ;;
    --lock-ttl-seconds) lock_ttl_seconds="${2:-}"; shift 2 ;;
    --schedule-lookback-minutes) schedule_lookback_minutes="${2:-}"; shift 2 ;;
    --no-start) start_service=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$site" ]] || die "--site is required"
[[ -n "$result_server_url" ]] || die "--result-server-url is required"

if [[ -z "$repo_dir" ]]; then
  repo_dir="$PWD"
fi
if [[ -z "$venv_dir" ]]; then
  venv_dir="$HOME/fugakunext/venv"
fi
if [[ -z "$db_path" ]]; then
  db_path="$HOME/fugakunext/$site/cx_portal.sqlite3"
fi
if [[ -z "$env_file" ]]; then
  env_file="$HOME/.config/fncx/$site.env"
fi

[[ -d "$repo_dir/.git" ]] || die "--repo-dir must point at a Benchkit checkout"
[[ -x "$venv_dir/bin/python" ]] || die "Python not found: $venv_dir/bin/python"
[[ -f "$db_path" ]] || die "DB not found: $db_path"
[[ -f "$env_file" ]] || die "EnvironmentFile not found: $env_file"

unit_dir="$HOME/.config/systemd/user"
service_name="benchkit-trigger-runner-${site}.service"
timer_name="benchkit-trigger-runner-${site}.timer"
service_path="$unit_dir/$service_name"
timer_path="$unit_dir/$timer_name"

mkdir -p "$unit_dir"

runner_args=(--db "$db_path" --result-server-url "$result_server_url")
if [[ "$mode" == "submit" ]]; then
  runner_args+=(--submit)
else
  runner_args+=(--dry-run)
fi
if [[ "$record_observations" -eq 1 ]]; then
  runner_args+=(--record-observations)
fi
if [[ "$use_lock" -eq 0 ]]; then
  runner_args+=(--no-lock)
else
  runner_args+=(--lock-ttl-seconds "$lock_ttl_seconds")
fi
runner_args+=(--schedule-lookback-minutes "$schedule_lookback_minutes")

info "Writing $service_path"
{
  printf '[Unit]\n'
  printf 'Description=Benchkit Portal trigger runner (%s)\n' "$site"
  printf 'After=network-online.target\n'
  if [[ -n "$service_host" ]]; then
    printf 'ConditionHost=%s\n' "$service_host"
  fi
  printf '\n[Service]\n'
  printf 'Type=oneshot\n'
  printf 'WorkingDirectory=%s\n' "$repo_dir"
  printf 'EnvironmentFile=%s\n' "$env_file"
  printf 'ExecStart=%s/bin/python -m result_server.trigger_runner' "$venv_dir"
  printf ' %q' "${runner_args[@]}"
  printf '\n'
  printf 'StandardOutput=journal\n'
  printf 'StandardError=journal\n'
} > "$service_path"

info "Writing $timer_path"
{
  printf '[Unit]\n'
  printf 'Description=Run Benchkit Portal trigger runner (%s)\n' "$site"
  printf '\n[Timer]\n'
  printf 'OnCalendar=%s\n' "$on_calendar"
  printf 'Persistent=true\n'
  printf 'Unit=%s\n' "$service_name"
  printf '\n[Install]\n'
  printf 'WantedBy=timers.target\n'
} > "$timer_path"

systemctl --user daemon-reload

if [[ "$start_service" -eq 1 ]]; then
  systemctl --user enable "$timer_name"
  systemctl --user restart "$timer_name"
  info "Started $timer_name"
  systemctl --user list-timers "$timer_name" --no-pager
else
  info "Wrote units without starting. Enable with: systemctl --user enable --now $timer_name"
fi
