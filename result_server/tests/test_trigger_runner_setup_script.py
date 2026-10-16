"""Tests for the Portal trigger runner systemd setup helper."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest


def test_setup_trigger_runner_writes_user_units(tmp_path):
    repo_dir = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    venv = tmp_path / "venv"
    db_path = tmp_path / "cx_portal.sqlite3"
    env_file = home / ".config" / "fncx" / "dev2.env"
    systemctl_log = tmp_path / "systemctl.log"
    script = repo_dir / "scripts" / "site" / "setup_trigger_runner.sh"

    fake_bin.mkdir(parents=True)
    venv.joinpath("bin").mkdir(parents=True)
    env_file.parent.mkdir(parents=True)
    home.mkdir(exist_ok=True)
    db_path.write_text("", encoding="utf-8")
    env_file.write_text("RESULT_SERVER_GITLAB_TARGETS=swc=example/group\n", encoding="utf-8")
    venv.joinpath("bin", "python").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_bin.joinpath("systemctl").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$SYSTEMCTL_LOG\"\n",
        encoding="utf-8",
    )
    for executable in (venv / "bin" / "python", fake_bin / "systemctl"):
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["SYSTEMCTL_LOG"] = str(systemctl_log)
    subprocess.run(
        [
            str(script),
            "--site",
            "dev2",
            "--repo-dir",
            str(repo_dir),
            "--venv",
            str(venv),
            "--db",
            str(db_path),
            "--env-file",
            str(env_file),
            "--result-server-url",
            "https://example.invalid/dev2",
            "--on-calendar",
            "*:0/5",
            "--lock-ttl-seconds",
            "120",
            "--schedule-lookback-minutes",
            "7",
            "--submit",
        ],
        check=True,
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    service = home / ".config" / "systemd" / "user" / "benchkit-trigger-runner-dev2.service"
    timer = home / ".config" / "systemd" / "user" / "benchkit-trigger-runner-dev2.timer"
    service_text = service.read_text(encoding="utf-8")
    timer_text = timer.read_text(encoding="utf-8")
    log_text = systemctl_log.read_text(encoding="utf-8")

    assert f"WorkingDirectory={repo_dir}" in service_text
    assert f"EnvironmentFile={env_file}" in service_text
    assert "-m result_server.trigger_runner" in service_text
    assert "--submit" in service_text
    assert "--record-observations" in service_text
    assert "--lock-ttl-seconds 120" in service_text
    assert "--schedule-lookback-minutes 7" in service_text
    assert "https://example.invalid/dev2" in service_text
    assert "OnCalendar=*:0/5" in timer_text
    assert "Unit=benchkit-trigger-runner-dev2.service" in timer_text
    assert "daemon-reload" in log_text
    assert "enable benchkit-trigger-runner-dev2.timer" in log_text
    assert "restart benchkit-trigger-runner-dev2.timer" in log_text


def _local_checkouts(tmp_path):
    """Real local clone/worktree metadata; no external Git access."""
    source = tmp_path / 'source'
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    (source / 'README').write_text('setup fixture\n')
    subprocess.run(['git', '-C', str(source), 'add', 'README'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    clone = tmp_path / 'ordinary clone'
    subprocess.run(['git', 'clone', '-q', '--no-hardlinks', str(source), str(clone)], check=True)
    worktree = tmp_path / 'linked worktree'
    subprocess.run(['git', '-C', str(clone), 'worktree', 'add', '-qb', 'linked', str(worktree)], check=True)
    return clone, worktree


def _isolated_setup(tmp_path, repo_dir):
    home = tmp_path / 'home'
    fake_bin = tmp_path / 'bin'
    venv = tmp_path / 'venv'
    log = tmp_path / 'systemctl.log'
    db = tmp_path / 'fixture.sqlite3'
    env_file = tmp_path / 'fixture.env'
    fake_bin.mkdir()
    (venv / 'bin').mkdir(parents=True)
    db.write_bytes(b'not a database: must remain unchanged\n')
    env_file.write_text('RESULT_SERVER_GITLAB_TARGETS=fixture=example/group\n')
    (venv / 'bin' / 'python').write_text('#!/bin/bash\nexit 99\n')
    (fake_bin / 'systemctl').write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"\n')
    for executable in [venv / 'bin' / 'python', fake_bin / 'systemctl']:
        executable.chmod(0o700)
    env = dict(os.environ, HOME=str(home), PATH=f"{fake_bin}:{os.environ['PATH']}", SYSTEMCTL_LOG=str(log))
    script = Path(__file__).resolve().parents[2] / 'scripts/site/setup_trigger_runner.sh'
    result = subprocess.run(['bash', str(script), '--site', 'fixture', '--repo-dir', str(repo_dir),
                             '--venv', str(venv), '--db', str(db), '--env-file', str(env_file),
                             '--result-server-url', 'https://example.invalid', '--no-start'],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert db.read_bytes() == b'not a database: must remain unchanged\n'
    return result, home / '.config/systemd/user', log


@pytest.mark.parametrize('kind', ['clone', 'linked-worktree', 'symlink'])
def test_setup_accepts_checkout_roots_with_isolated_unit_generation(tmp_path, kind):
    clone, worktree = _local_checkouts(tmp_path)
    assert (clone / '.git').is_dir()
    assert (worktree / '.git').is_file()
    if kind == 'symlink':
        selected = tmp_path / 'checkout-link'
        selected.symlink_to(worktree, target_is_directory=True)
    else:
        selected = clone if kind == 'clone' else worktree
    result, units, log = _isolated_setup(tmp_path, selected)
    assert result.returncode == 0, result.stderr
    service = (units / 'benchkit-trigger-runner-fixture.service').read_text()
    timer = (units / 'benchkit-trigger-runner-fixture.timer').read_text()
    assert f'WorkingDirectory={selected}\n' in service
    assert '--dry-run' in service and '--submit' not in service
    assert 'Unit=benchkit-trigger-runner-fixture.service' in timer
    assert log.read_text().splitlines() == ['--user daemon-reload']


@pytest.mark.parametrize('kind', ['missing', 'plain', 'fake-git-directory', 'broken-git-file', 'subdirectory', 'bare'])
def test_setup_rejects_invalid_paths_before_unit_or_service_changes(tmp_path, kind):
    selected = tmp_path / 'invalid'
    if kind == 'subdirectory':
        clone, _ = _local_checkouts(tmp_path)
        selected = clone / 'subdirectory'
        selected.mkdir()
    elif kind == 'bare':
        subprocess.run(['git', 'init', '--bare', '-q', str(selected)], check=True)
    elif kind != 'missing':
        selected.mkdir()
        if kind == 'fake-git-directory':
            (selected / '.git').mkdir()
        elif kind == 'broken-git-file':
            (selected / '.git').write_text('gitdir: missing-git-directory\n')
    result, units, log = _isolated_setup(tmp_path, selected)
    assert result.returncode != 0
    assert '--repo-dir must point at a Benchkit checkout' in result.stderr
    assert not units.exists()
    assert not log.exists()
