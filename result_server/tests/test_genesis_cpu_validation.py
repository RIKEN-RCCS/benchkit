"""Completion checks reject incomplete and invalid GENESIS observations."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('mutation', ['none', 'short', 'nan', 'overflow', 'missing_header',
                                    'short_row', 'zero_time', 'missing_time', 'error'])
def test_genesis_completion_checks(tmp_path, mutation):
    inp = tmp_path / 'inp'
    inp.write_text('[DYNAMICS]\nnsteps = 20\n')
    text = 'INFO: STEP TIME TOTAL_ENE TEMPERATURE\nINFO: 10 0.01 -12.3 300\nINFO: 20 0.02 -12.4 301\n dynamics = 1.25\n'
    if mutation == 'short':
        text = text.replace('INFO: 20', 'INFO: 19')
    elif mutation == 'nan':
        text = text.replace('-12.3', 'NaN')
    elif mutation == 'overflow':
        text = text.replace('-12.3', '********')
    elif mutation == 'missing_header':
        text = text.split('\n', 1)[1]
    elif mutation == 'short_row':
        text = text.replace('-12.3 300', '-12.3')
    elif mutation == 'zero_time':
        text = text.replace('1.25', '0')
    elif mutation == 'missing_time':
        text = text.replace(' dynamics = 1.25\n', '')
    elif mutation == 'error':
        text += 'MPI_ABORT\n'
    log = tmp_path / 'log'
    log.write_text(text)
    process = subprocess.run(['bash', str(ROOT / 'programs/genesis/validate_cpu_run.sh'),
                              str(log), str(inp)], capture_output=True, text=True)
    assert (process.returncode == 0) == (mutation == 'none')


@pytest.mark.parametrize("system,threads", [("Camphor3", "14"), ("Flow2_Type1", "6")])
def test_cpu_run_preserves_build_source_and_emits_observations(tmp_path, system, threads):
    import os
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    (tmp_path / 'programs').symlink_to(ROOT / 'programs', target_is_directory=True)
    repo = tmp_path / 'genesis_benchmark_input'
    work = repo / 'npt/genesis2.0beta_3.5fs/apoa1'
    inputs = repo / 'inputs/apoa1'
    work.mkdir(parents=True)
    inputs.mkdir(parents=True)
    (work / 'p8.inp').write_text('[DYNAMICS]\nnsteps = 20\n')
    for name in ['top_all27_prot_lipid.rtf', 'par_all27_prot_lipid.prm',
                 'apoa1.psf', 'apoa1.pdb', 'apoa1.rst']:
        (inputs / name).write_text('fixture\n')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    git('init', '-q', '-b', 'main')
    git('add', '.')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-qm', 'input')
    sha = git('rev-parse', 'HEAD')
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    exe = artifacts / 'spdyn'
    exe.write_text('''#!/bin/bash
printf 'INFO: STEP TIME TOTAL_ENE TEMPERATURE\nINFO: 20 0.02 -12 300\n dynamics = 1.25\n pairlist = 0.1\n bond = 0.1\n angle = 0.1\n dihedral = 0.1\n pme real = 0.1\n pme recip = 0.1\n integrator = 0.1\n'
''')
    exe.chmod(0o755)
    results = tmp_path / 'results'
    results.mkdir()
    (results / 'source_info.env').write_text('build source marker\n')
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    launch = bindir / ('srun' if system == 'Camphor3' else 'mpirun')
    launch.write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$LAUNCH_LOG"\nshift '+('4' if system == 'Camphor3' else '2')+'\nexec "$@"\n')
    launch.chmod(0o755)
    envfile = tmp_path / 'bash-env'
    envfile.write_text('module() { :; }\n')
    env = dict(os.environ, BASH_ENV=str(envfile), PATH=str(bindir)+':'+os.environ['PATH'],
               GENESIS_INPUT_COMMIT=sha, LAUNCH_LOG=str(tmp_path / 'launch.log'))
    process = subprocess.run(['bash', str(ROOT / 'programs/genesis/run.sh'), system,
                              '1', '8', threads], cwd=tmp_path, env=env,
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr
    assert (results / 'source_info.env').read_text() == 'build source marker\n'
    result = (results / 'result').read_text()
    assert 'FOM:1.25' in result and 'Exp:p8' in result
    assert 'OBSERVATION' in result and 'SECTION:' in result
    expected = '-n 8 --ntasks-per-node=8 --cpus-per-task=14' if system == 'Camphor3' else '-n 8'
    assert expected in (tmp_path / 'launch.log').read_text()
