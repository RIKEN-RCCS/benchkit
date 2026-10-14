"""Exercise Flow2's existing KH input, launch and observation contract."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_flow2_mhd_runs_fixed_case_and_records_inputs(tmp_path):
    app = tmp_path / 'programs/MHDTurbulence'
    app.mkdir(parents=True)
    shutil.copy2(ROOT / 'programs/MHDTurbulence/run.sh', app / 'run.sh')
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    inputs = tmp_path / 'artifacts/mhd_cpu_input'
    inputs.mkdir(parents=True)
    (inputs / 'config.f90').write_text('compiled config fixture\n')
    (inputs / 'main.f90').write_text('compiled main fixture\n')
    exe = tmp_path / 'artifacts/Simulation.x'
    exe.write_text('#!/bin/bash\necho "sim time [s]: 5.0"\necho "time/count/cell 0.01"\n')
    exe.chmod(0o755)
    tools = tmp_path / 'tools'
    tools.mkdir()
    mpi = tools / 'mpirun'
    mpi.write_text('#!/bin/bash\n[[ $1 = -np && $2 = 96 && $OMP_NUM_THREADS = 1 ]] || exit 2\nshift 2\nexec "$@"\n')
    mpi.chmod(0o755)
    init = tmp_path / 'bash-env'
    init.write_text('module() { :; }\n')
    env = dict(os.environ, BASH_ENV=str(init), PATH=str(tools)+':'+os.environ['PATH'])
    run = subprocess.run(['bash', str(app / 'run.sh'), 'Flow2_Type1', '1', '96', '1'],
                         cwd=tmp_path, env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    result = (tmp_path / 'results/result').read_text()
    assert float(result.split()[0].split(':')[1]) == 100
    assert 'SECTION:total time:5.0' in result
    import json
    records = json.loads((tmp_path / 'results/input_info.json').read_text())['inputs']
    assert len(records) == 2 and {r['result_exp'] for r in records} == {'KH'}
    bad = subprocess.run(['bash', str(app / 'run.sh'), 'Flow2_Type1', '1', '48', '1'],
                         cwd=tmp_path, env=env, capture_output=True, text=True)
    assert bad.returncode != 0 and '96 MPI ranks' in bad.stderr
