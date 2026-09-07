"""Tests for the site runner setup doctor helper."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_runner_layout(base_dir: Path, home: Path) -> None:
    bin_dir = base_dir / "bin"
    bin_dir.mkdir(parents=True)
    (base_dir / "builds").mkdir()
    (base_dir / "cache").mkdir()

    for name in ("gitlab-runner", "jacamar"):
        path = bin_dir / name
        path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        _make_executable(path)

    (base_dir / "config.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="{base_dir}"
BASE_BUILD_DIR="${{BASE_DIR}}/builds"
BASE_CACHE_DIR="${{BASE_DIR}}/cache"
SLUG="${{CUSTOM_ENV_CI_PROJECT_PATH_SLUG:-unknown}}"
JOB_ID="${{CUSTOM_ENV_CI_JOB_ID:-$$}}"
UNIQUE_BUILD_DIR="${{BASE_BUILD_DIR}}/${{SLUG}}/job_${{JOB_ID}}"
UNIQUE_CACHE_DIR="${{BASE_CACHE_DIR}}/${{SLUG}}/job_${{JOB_ID}}"
cat <<EOS
{{
  "builds_dir": "${{UNIQUE_BUILD_DIR}}",
  "cache_dir": "${{UNIQUE_CACHE_DIR}}",
  "builds_dir_is_shared": false,
  "job_env": {{
    "CUSTOM_RUNNER_PROJECT_SLUG": "${{SLUG}}",
    "CUSTOM_UNIQUE_BUILD_DIR": "${{UNIQUE_BUILD_DIR}}",
    "CUSTOM_UNIQUE_CACHE_DIR": "${{UNIQUE_CACHE_DIR}}",
    "CUSTOM_DIR": "${{BASE_DIR}}"
  }}
}}
EOS
""".format(base_dir=base_dir),
        encoding="utf-8",
    )
    (base_dir / "prepare.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n", encoding="utf-8"
    )
    (base_dir / "run.sh").write_text(
        """#!/usr/bin/env bash
RUNNER_ENV="${{CUSTOM_DIR:-{base_dir}}}/runner-env.sh"
if [[ -r "${{RUNNER_ENV}}" ]]; then
  source "${{RUNNER_ENV}}"
fi
set -eo pipefail
exec "$@"
""".format(base_dir=base_dir),
        encoding="utf-8",
    )
    (base_dir / "cleanup.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="{base_dir}"
BUILD_DIR="${{CUSTOM_UNIQUE_BUILD_DIR:-}}"
CACHE_DIR="${{CUSTOM_UNIQUE_CACHE_DIR:-}}"
case "$BUILD_DIR" in
  "${{BASE_DIR}}/builds/"*) [[ -d "$BUILD_DIR" ]] && rm -rf -- "$BUILD_DIR" ;;
esac
case "$CACHE_DIR" in
  "${{BASE_DIR}}/cache/"*) [[ -d "$CACHE_DIR" ]] && rm -rf -- "$CACHE_DIR" ;;
esac
""".format(base_dir=base_dir),
        encoding="utf-8",
    )
    (base_dir / "runner-env.sh").write_text(
        """#!/usr/bin/env bash
if ! type module >/dev/null 2>&1; then
  source /etc/profile.d/modules.sh || true
fi
source "${HOME}/.bashrc" || true
""",
        encoding="utf-8",
    )
    for name in ("config.sh", "prepare.sh", "run.sh", "cleanup.sh", "runner-env.sh"):
        _make_executable(base_dir / name)

    (base_dir / "config.toml").write_text(
        f"""[[runners]]
  executor = "custom"
  shell = "bash"
  environment = ["PATH={base_dir}/bin:/usr/local/bin:/usr/bin:/bin"]
  [runners.custom]
    config_exec = "{base_dir}/config.sh"
    prepare_exec = "{base_dir}/prepare.sh"
    run_exec = "{base_dir}/run.sh"
    cleanup_exec = "{base_dir}/cleanup.sh"

[[runners]]
  executor = "custom"
  shell = "bash"
  environment = ["PATH={base_dir}/bin:/usr/local/bin:/usr/bin:/bin"]
  [runners.custom]
    config_exec = "{base_dir}/bin/jacamar"
    config_args = ["--no-auth", "config", "--configuration", "{base_dir}/custom-config.toml"]
    prepare_exec = "{base_dir}/bin/jacamar"
    run_exec = "{base_dir}/bin/jacamar"
    cleanup_exec = "{base_dir}/bin/jacamar"
""",
        encoding="utf-8",
    )
    (base_dir / "custom-config.toml").write_text(
        f"""[general]
executor = "slurm"
data_dir = "{base_dir}"
retain_logs = true
unrestricted_cmd_line = false

[auth]
downscope = "setuid"
user_allowlist = ["runner"]

[batch]
command_delay = "30s"
""",
        encoding="utf-8",
    )

    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "gitlab-runner-devsite-amd.service").write_text(
        f"""[Unit]
Description=GitLab Runner service for devsite
ConditionHost=login01

[Service]
ExecStart={base_dir}/bin/gitlab-runner run --config {base_dir}/config.toml
""",
        encoding="utf-8",
    )


def test_site_runner_doctor_accepts_setup_runner_layout(tmp_path):
    home = tmp_path / "home"
    base_dir = tmp_path / "runner"
    home.mkdir()
    _write_runner_layout(base_dir, home)

    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "site" / "doctor_runner.sh"),
            "--site",
            "devsite",
            "--arch",
            "amd64",
            "--base-dir",
            str(base_dir),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "HOME": str(home)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failure(s)" in result.stdout
    assert "CUSTOM_DIR for persistent build cache discovery" in result.stdout
    assert "persistent build_cache directory can be created" in result.stdout
    assert "token" not in result.stdout.lower()


def test_site_runner_doctor_fails_when_custom_dir_is_missing(tmp_path):
    home = tmp_path / "home"
    base_dir = tmp_path / "runner"
    home.mkdir()
    _write_runner_layout(base_dir, home)
    (base_dir / "config.sh").write_text(
        (base_dir / "config.sh").read_text(encoding="utf-8").replace(
            '    "CUSTOM_DIR": "${BASE_DIR}"\n', ""
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "site" / "doctor_runner.sh"),
            "--arch",
            "amd64",
            "--base-dir",
            str(base_dir),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "HOME": str(home)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "config helper should export CUSTOM_DIR" in result.stdout
    assert "systemd unit check skipped" in result.stdout


def test_site_runner_doctor_warns_when_cleanup_mentions_build_cache(tmp_path):
    home = tmp_path / "home"
    base_dir = tmp_path / "runner"
    home.mkdir()
    _write_runner_layout(base_dir, home)
    with (base_dir / "cleanup.sh").open("a", encoding="utf-8") as handle:
        handle.write("# build_cache should be reviewed before cleanup changes\n")

    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "site" / "doctor_runner.sh"),
            "--arch",
            "amd64",
            "--base-dir",
            str(base_dir),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "HOME": str(home)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "cleanup helper mentions build_cache" in result.stdout
