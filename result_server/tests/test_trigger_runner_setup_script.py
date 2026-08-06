"""Tests for the Portal trigger runner systemd setup helper."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


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
            "https://fncx.r-ccs.riken.jp/dev2",
            "--on-calendar",
            "*:0/5",
            "--lock-ttl-seconds",
            "120",
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
    assert "https://fncx.r-ccs.riken.jp/dev2" in service_text
    assert "OnCalendar=*:0/5" in timer_text
    assert "Unit=benchkit-trigger-runner-dev2.service" in timer_text
    assert "daemon-reload" in log_text
    assert "enable benchkit-trigger-runner-dev2.timer" in log_text
    assert "restart benchkit-trigger-runner-dev2.timer" in log_text
