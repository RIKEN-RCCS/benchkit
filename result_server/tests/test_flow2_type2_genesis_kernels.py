"""Check Type II kernel launch, existing acceptance and input association."""
import bz2
import json
import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('bad_case', ['', 'Oct'])
def test_three_type2_cases_preserve_checks_and_inputs(tmp_path, bad_case):
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    repo = tmp_path / 'genesis-nonbonded-kernels'
    (repo / 'data').mkdir(parents=True)
    for name in ['data_kernel_generic', 'data_kernel_Oct']:
        (repo / 'data' / (name + '.bz2')).write_bytes(bz2.compress((name + '\n').encode()))
    for directory in ['Generic', 'Intel', 'Intel_mod1']:
        (repo / directory).mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    git('init', '-q', '-b', 'main')
    git('add', '.')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    for case in ['Generic', 'Oct', 'Oct_mod1']:
        executable = artifacts / ('kernel_' + case)
        successes = 2 if case == bad_case else 3
        executable.write_text('#!/bin/bash\n[[ $OMP_NUM_THREADS = 72 && $OMP_PLACES = cores && $OMP_PROC_BIND = close ]] || exit 3\n' +
                              'echo "the computed result seems to be OK."\n' * successes + 'echo "time= 1.25"\n')
        executable.chmod(0o755)
    init = tmp_path / 'init'
    init.write_text('module() { :; }\n')
    env = dict(os.environ, BASH_ENV=str(init), GENESIS_NONBONDED_KERNELS_SOURCE_COMMIT=git('rev-parse', 'HEAD'))
    run = subprocess.run(['bash', str(ROOT / 'programs/genesis-nonbonded-kernels/run.sh'),
                          'Flow2_Type2', '1', '1', '72'], cwd=tmp_path, env=env, capture_output=True, text=True)
    if bad_case:
        assert run.returncode != 0 and 'Correctness check failed for Oct' in run.stderr
        assert 'Exp:Oct ' not in (tmp_path / 'results/result').read_text()
    else:
        assert run.returncode == 0, run.stderr
        text = (tmp_path / 'results/result').read_text()
        assert text.count('FOM:1.25') == 3
        inputs = json.loads((tmp_path / 'results/input_info.json').read_text())['inputs']
        assert {i['result_exp'] for i in inputs} == {'Generic', 'Oct', 'Oct_mod1'}
        assert all(i['observation_capture']['collection_status'] == 'recorded' for i in inputs)
