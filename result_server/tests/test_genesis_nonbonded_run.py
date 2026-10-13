"""Exercise the app entrypoint without scheduling jobs or executing a benchmark."""
import base64
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def app(tmp_path):
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    repo = tmp_path / 'genesis-nonbonded-kernels'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    for directory in ('Generic', 'Intel', 'Intel_mod1', 'data'):
        (repo / directory).mkdir()
    for name in ('data_kernel_generic', 'data_kernel_Oct'):
        (repo / 'data' / name).write_text('observed input\n')
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-qm', 'reference input')
    reference = git(repo, 'rev-parse', 'HEAD')
    (repo / 'data' / 'data_kernel_generic').write_text('different input\n')
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-qm', 'newer input')
    results = tmp_path / 'results'
    results.mkdir()
    fields = {'BK_SOURCE_TYPE': 'git', 'BK_SOURCE_REF_NAME': 'main',
              'BK_SOURCE_RESOLVED_COMMIT': reference}
    (results / 'source_info.env').write_text('BK_SOURCE_INFO_FORMAT=base64-v1\n' + ''.join(
        key + '_B64=' + base64.b64encode(value.encode()).decode() + '\n'
        for key, value in fields.items()))
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    kernel = '''#!/bin/bash
case "$CASE" in
    exit) exit 23 ;;
esac
printf 'time= %s\\n' "${FOM:-1.25}"
printf 'kernel diagnostic\\n' >&2
for component in 1 2 3; do
    if [ "$CASE" = wrong ] && [ "$component" = 3 ]; then
        echo 'the computed result is not close enough to the expected value.'
    elif [ "$CASE" != missing ] || [ "$component" != 3 ]; then
        echo 'the computed result seems to be OK.'
    fi
done
'''
    for name in ('Generic', 'Oct', 'Oct_mod1'):
        path = artifacts / ('kernel_' + name)
        path.write_text(kernel)
        path.chmod(0o755)
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    launch = bindir / 'srun'
    launch.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$LAUNCH_LOG"\nshift 2\nexec "$@"\n')
    launch.chmod(0o755)
    envfile = tmp_path / 'bash-env'
    envfile.write_text('module() { :; }\n')
    env = dict(os.environ, BASH_ENV=str(envfile), CASE='ok',
               PATH=str(bindir) + ':' + os.environ['PATH'], LAUNCH_LOG=str(tmp_path / 'launch.log'))
    return tmp_path, repo, reference, env


def run(app, system='Camphor3', **values):
    directory, _, _, env = app
    return subprocess.run(['bash', str(ROOT / 'programs/genesis-nonbonded-kernels/run.sh'),
                           system, '1', '1', '6'], cwd=directory,
                          env=dict(env, **values), capture_output=True, text=True)


@pytest.mark.parametrize('system', ['Camphor3', 'Fugaku'])
def test_all_kernels_use_recorded_input_and_validate_results(app, system):
    directory, repo, reference, _ = app
    result = run(app, system=system)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo, 'rev-parse', 'HEAD') == reference
    assert (repo / 'data/data_kernel_generic').read_text() == 'observed input\n'
    output = (directory / 'results/result').read_text()
    for name in ('Generic', 'Oct', 'Oct_mod1'):
        assert 'Exp:' + name in output
        assert 'kernel diagnostic' in (directory / 'results' / ('log_' + name + '.txt')).read_text()
    assert output.count('FOM:1.25') == 3
    if system == 'Camphor3':
        assert (directory / 'launch.log').read_text().count('--ntasks=1 --cpus-per-task=6 ./kernel') == 3
    else:
        assert not (directory / 'launch.log').exists()


@pytest.mark.parametrize('values', [dict(CASE='wrong'), dict(CASE='missing'),
                                    dict(CASE='exit'), dict(FOM='0'),
                                    dict(FOM='NaN'), dict(FOM='1oops')])
def test_invalid_kernel_results_are_not_emitted(app, values):
    directory, _, _, _ = app
    result = run(app, **values)
    assert result.returncode != 0
    assert not (directory / 'results/result').exists()
