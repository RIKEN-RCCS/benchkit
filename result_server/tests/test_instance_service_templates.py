"""Check opt-in units with fixture environments, never a service manager or live DB."""

import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'deploy/instances'


def values(name, section, key):
    current = None
    result = []
    for line in (EXAMPLES / name).read_text().splitlines():
        if line.startswith('['):
            current = line.strip('[]')
        elif current == section and line.startswith(key + '='):
            result.append(line.split('=', 1)[1])
    return result


def unit(role):
    return f'benchkit-cx-{role}@.service.example'


def test_units_share_one_deployment_and_only_intended_environment_files():
    common = ['%h/.config/benchkit/cx/%i/connections.env',
              '%h/.config/benchkit/cx/%i/instance.env']
    for role in ('public', 'console', 'trigger'):
        name = unit(role)
        assert values(name, 'Service', 'WorkingDirectory') == [
            '%h/.local/lib/benchkit/cx/%i/current/code/result_server']
        expected = common + ([] if role == 'trigger' else ['%h/.config/benchkit/cx/%i/web.env'])
        expected += [f'%h/.config/benchkit/cx/%i/{role}.env']
        assert values(name, 'Service', 'EnvironmentFile') == expected
        assert all(not value.startswith('-') for value in expected)
        args = shlex.split(values(name, 'Service', 'ExecStart')[0])
        assert args[0].startswith('%h/.local/lib/benchkit/cx/%i/current/venv/bin/')
        assert values(name, 'Service', 'UMask') == ['0077']
        assert values(name, 'Service', 'NoNewPrivileges') == ['yes']
        if role == 'trigger':
            assert '--db' not in args and '--result-server-url' not in args
            assert args[1:4] == ['-B', '-m', 'trigger_runner']
            assert '${BENCHKIT_TRIGGER_MODE}' in args
            assert '--lock-ttl-seconds' in args and '--record-observations' in args
            assert 'BENCHKIT_TRIGGER_MODE=--dry-run' in values(name, 'Service', 'Environment')
        else:
            assert args[-1] == f"app:create_instance_app('{role}')"
    timer = 'benchkit-cx-trigger@.timer.example'
    assert values(timer, 'Timer', 'Unit') == ['benchkit-cx-trigger@%i.service']
    assert values(timer, 'Timer', 'OnCalendar') == ['minutely']
    assert values(timer, 'Timer', 'Persistent') == ['true']


def test_environment_examples_keep_role_secrets_out_of_common_files():
    for name in ('connections', 'instance', 'public'):
        assignments = [line for line in (EXAMPLES / f'{name}.env.example').read_text().splitlines()
                       if line and not line.startswith('#')]
        assert not any(re.search('SECRET|TOKEN|KEYS|GRANT|SUBMISSION', line) for line in assignments)
    assert 'BENCHKIT_TRIGGER_MODE=--dry-run' in (EXAMPLES / 'trigger.env.example').read_text()


@pytest.mark.parametrize('role,trigger_mode', [
    ('public', '--dry-run'), ('console', '--dry-run'),
    ('trigger', '--dry-run'), ('trigger', '--submit'),
])
def test_template_entrypoints_use_fixture_instance_without_submission(tmp_path, role, trigger_mode):
    home = tmp_path / 'home'
    deployment = home / '.local/lib/benchkit/cx/dev2/deployments/fixture'
    deployment.mkdir(parents=True)
    (deployment / 'code').symlink_to(ROOT, target_is_directory=True)
    (deployment / 'venv').symlink_to(Path(sys.executable).parent.parent, target_is_directory=True)
    (deployment.parent.parent / 'current').symlink_to('deployments/fixture', target_is_directory=True)
    service = unit(role)
    cwd = values(service, 'Service', 'WorkingDirectory')[0].replace('%h', str(home)).replace('%i', 'dev2')
    env = {
        'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(Path(cwd)),
        'PYTHONDONTWRITEBYTECODE': '1', 'RESULT_SERVER_INSTANCE': 'dev2',
        'RESULT_SERVER_DATA_DIR': str(tmp_path / 'data'),
        'RESULT_SERVER_PUBLIC_URL': 'https://results.example.org/dev2',
        'RESULT_SERVER_REDIS_PREFIX': 'fixture:', 'RESULT_SERVER_SESSION_COOKIE_NAME': 'fixture_session',
        'TOTP_ISSUER': 'Fixture', 'CASE_ROOT': str(tmp_path),
        'BENCHKIT_TRIGGER_MODE': trigger_mode, 'BENCHKIT_WEB_BIND': '127.0.0.1:18002',
        'BENCHKIT_WEB_WORKERS': '2',
    }
    if role != 'trigger':
        env.update(FLASK_SECRET_KEY=secrets.token_hex(32), RESULT_SERVER_KEYS='fixture:' + secrets.token_hex(32))
    command = values(service, 'Service', 'ExecStart')[0].replace('%h', str(home)).replace('%i', 'dev2')
    for key in ('BENCHKIT_TRIGGER_MODE', 'BENCHKIT_WEB_BIND', 'BENCHKIT_WEB_WORKERS'):
        command = command.replace('${' + key + '}', env[key])
    args = shlex.split(command)
    assert Path(args[0]).parent.resolve() == Path(sys.executable).parent.resolve()
    script = '''
import os,sys
from pathlib import Path
from unittest.mock import patch
from utils.instance_config import resolve_instance_settings
settings = resolve_instance_settings()
assert settings.profile_db_path == os.environ['RESULT_SERVER_DATA_DIR'] + '/cx_portal.sqlite3'
assert settings.redis_prefix == 'fixture:' and settings.session_cookie_name == 'fixture_session'
'''
    if role == 'trigger':
        script += '''
import trigger_runner
with patch.object(trigger_runner, 'run_triggers', return_value=[]) as evaluate:
    assert trigger_runner.main(sys.argv[1:]) == 0
    call = evaluate.call_args.kwargs
    assert call['db_path'] == settings.profile_db_path
    submit = os.environ['BENCHKIT_TRIGGER_MODE'] == '--submit'
    assert call['dry_run'] == (not submit) and call['submit'] == submit
    assert call['use_lock'] is True and call['record_observations'] is True
    assert call['lock_ttl_seconds'] == 300 and call['schedule_lookback_minutes'] == 5
assert not Path(os.environ['RESULT_SERVER_DATA_DIR']).exists()
'''
        extra = args[4:]
    else:
        script += '''
import fakeredis
from gunicorn.util import import_app
with patch('redis.from_url', return_value=fakeredis.FakeRedis(decode_responses=True)):
    application = import_app(sys.argv[1])
config = application.config
assert config['EXECUTION_PROFILE_DB_PATH'] == settings.profile_db_path
assert config['TOTP_ISSUER'] == 'Fixture-Dev2'
assert config['REDIS_PREFIX'] == settings.redis_prefix
assert config['SESSION_COOKIE_NAME'] == settings.session_cookie_name
assert Path(config['RECEIVED_DIR']) == Path(settings.data_dir) / 'received'
public = sys.argv[2] == 'public'
assert config['PUBLIC_PORTAL_MODE'] == public
prefix = '/dev2' + ('' if public else '/console')
response = application.test_client().get(prefix + '/budgets/')
assert response.status_code == (404 if public else 302)
'''
        extra = [args[-1], role]
    result = subprocess.run([sys.executable, '-B', '-c', script, *extra], env=env,
                            cwd=cwd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_environment_layers_keep_console_grants_and_web_secrets_in_their_roles(tmp_path):
    folder = tmp_path / '.config/benchkit/cx/dev2'
    folder.mkdir(parents=True)
    contents = {
        'connections': 'RESULT_SERVER_BUDGET_DB_PATH=/example/shared/registry.sqlite3\n',
        'instance': 'RESULT_SERVER_INSTANCE=dev2\nRESULT_SERVER_DATA_DIR=/example/data/dev2\n',
        'web': 'FLASK_SECRET_KEY=fixture-web-only\n',
        'public': 'BENCHKIT_WEB_BIND=127.0.0.1:18002\n',
        'console': 'FIXTURE_CONSOLE_GRANT=console-only\n',
        'trigger': 'BENCHKIT_TRIGGER_MODE=--dry-run\nFIXTURE_TRIGGER_GRANT=trigger-only\n',
    }
    for name, text in contents.items():
        (folder / (name + '.env')).write_text(text)
    selected = {}
    for role in ('public', 'console', 'trigger'):
        env = {}
        for reference in values(unit(role), 'Service', 'EnvironmentFile'):
            path = Path(reference.replace('%h', str(tmp_path)).replace('%i', 'dev2'))
            for line in path.read_text().splitlines():
                key, value = line.split('=', 1)
                env[key] = shlex.split(value)[0]
        selected[role] = env
        assert ('FLASK_SECRET_KEY' in env) == (role != 'trigger')
        assert ('FIXTURE_CONSOLE_GRANT' in env) == (role == 'console')
        assert ('FIXTURE_TRIGGER_GRANT' in env) == (role == 'trigger')
    for key in ('RESULT_SERVER_INSTANCE', 'RESULT_SERVER_DATA_DIR', 'RESULT_SERVER_BUDGET_DB_PATH'):
        assert len({env[key] for env in selected.values()}) == 1


def test_systemd_syntax_with_temporary_executables_only(tmp_path):
    analyzer = shutil.which('systemd-analyze')
    if not analyzer:
        pytest.skip('systemd-analyze is unavailable')
    pair = tmp_path / '.local/lib/benchkit/cx/dev2/current'
    (pair / 'code/result_server').mkdir(parents=True)
    (pair / 'venv/bin').mkdir(parents=True)
    for name in ('python', 'gunicorn'):
        (pair / 'venv/bin' / name).symlink_to(shutil.which('true'))
    paths = []
    for source in sorted(EXAMPLES.glob('*.service.example')) + sorted(EXAMPLES.glob('*.timer.example')):
        path = tmp_path / source.name.removesuffix('.example').replace('@.', '@dev2.')
        path.write_text(source.read_text().replace('%h', str(tmp_path)))
        paths.append(str(path))
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path),
           'XDG_CONFIG_HOME': str(tmp_path / '.config'), 'XDG_RUNTIME_DIR': str(runtime)}
    result = subprocess.run([analyzer, '--user', '--man=no', 'verify', *paths],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
