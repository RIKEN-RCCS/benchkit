"""SCALE's read-only inputs, GPU sharing and failure handling without GPU/MPI."""
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'programs/scale-letkf'


@pytest.fixture
def runtime(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', '-b', 'master', str(source)], check=True)
    test = source / 'test/benchmark.RC_GH200_128x128'
    test.mkdir(parents=True)
    (test / 'prep.sh').write_text('''mkdir -p conf bin log result/local
cat > conf/example.conf <<EOF
BASENAME_ORG = "$PWD/result/SC23/20210730060000/bdyorg/mean/bdyorg",
OBS_IN_NAME = "$PWD/result/SC23/obs_radar/radar_20210730060030.dat",
GTOPO30_IN_DIR = "$PWD/scale_database/topo/GTOPO30/Products",
RESTART_OUT_BASENAME = "$PWD/result/local/init",
GUES_MEAN_INOUT_BASENAME = "$PWD/result/local/mean",
EOF
for name in scale-rm_pp_ens scale-rm_init_ens scale-rm_ens; do cp conf/example.conf conf/${name}_20210730060000.conf; done
cp conf/example.conf conf/letkf_20210730060030.conf
''')
    for name in ('scale-rm_pp_ens', 'scale-rm_init_ens', 'scale-rm_ens', 'letkf'):
        folder = 'letkf' if name == 'letkf' else 'ensmodel'
        p = source / ('scale/scale-letkf/scale/' + folder) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('#!/bin/bash\n[[ ${FAIL_STAGE:-} != "${0##*/}" ]] || exit 23\nsleep 0.04\necho completed\n')
        p.chmod(0o755)
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c',
                    'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    setup = 'source scripts/bk_functions.sh; bk_build_source "$1" master; cd "$BK_SOURCE_DIR"; bk_publish_source_runtime'
    subprocess.run(['bash', '-ec', setup, 'fixture', str(source)], cwd=tmp_path, check=True, capture_output=True)
    shared = tmp_path / 'shared'
    (shared / 'scale_database').mkdir(parents=True)
    for member in ('mean', '0001', '0002'):
        p = shared / 'result/SC23/20210730060000/bdyorg' / member
        p.mkdir(parents=True)
        (p / 'bdyorg.pe000000.nc').write_text('reference input\n')
    obs = shared / 'result/SC23/obs_radar'
    obs.mkdir(parents=True)
    (obs / 'radar_20210730060030.dat').write_text('observations\n')
    tools = tmp_path / 'tools'
    tools.mkdir()
    commands = {
        'mpiexec': '#!/bin/bash\nprintf "%s %s\\n" "$*" "$CUDA_VISIBLE_DEVICES" >> "$TRACE"\nshift 3\nexec "$@"\n',
        'nvidia-smi': '#!/bin/bash\necho GPU-fixture\n',
        'nvidia-cuda-mps-control': '#!/bin/bash\nif [[ ${1:-} == -d ]]; then echo start >> "$MPS_TRACE"; else read -r command; echo "$command" >> "$MPS_TRACE"; fi\n',
        'tar': '#!/bin/bash\necho forbidden-extraction >&2\nexit 99\n',
        'nc-config': '#!/bin/bash\ncase "$1" in --prefix) echo /fixture;; --cflags|--fflags|--libs|--flibs) :;; esac\n',
    }
    for name, text in commands.items():
        p = tools / name
        p.write_text(text)
        p.chmod(0o755)
    init = tmp_path / 'init.sh'
    init.write_text('module() { :; }\n')
    env = dict(os.environ, BASH_ENV=str(init), PATH=str(tools) + ':' + os.environ['PATH'],
               SCALE_LETKF_NC_CONFIG=str(tools / 'nc-config'), SCALE_LETKF_NF_CONFIG=str(tools / 'nc-config'),
               SCALE_LETKF_MATHLIB_LIBS='-lblas', SCALE_LETKF_INPUT_ROOT=str(shared),
               CUDA_VISIBLE_DEVICES='7', TRACE=str(tmp_path / 'trace'), MPS_TRACE=str(tmp_path / 'mps'))
    return tmp_path, shared, env


def run(runtime, **variables):
    directory, _, env = runtime
    return subprocess.run(['bash', str(APP / 'run.sh'), 'RIKYU', '1', '1', '32'],
                          cwd=directory, env=dict(env, **variables), capture_output=True, text=True)


def test_direct_input_locations_and_private_outputs(runtime):
    directory, shared, _ = runtime
    before = {p.relative_to(shared): p.read_bytes() for p in shared.rglob('*') if p.is_file()}
    result = run(runtime)
    assert result.returncode == 0, result.stdout + result.stderr
    text = (directory / 'results/result').read_text()
    assert 'FOM_unit:s' in text and 'numproc_node:12 nthreads:1' in text
    assert float(text.split('FOM:')[1].split()[0]) > 0
    assert (directory / 'mps').read_text() == 'start\nquit\n'
    trace = (directory / 'trace').read_text().splitlines()
    assert len(trace) == 4 and trace[0].startswith('-n 4')
    assert all(line.endswith('GPU-fixture') for line in trace)
    work = next(directory.glob('scale-rikyu.*'))
    for p in (work / 'conf').glob('*.conf'):
        for line in p.read_text().splitlines():
            if line.startswith(('BASENAME_ORG', 'OBS_IN_NAME', 'GTOPO30_IN_DIR')):
                assert str(shared) in line
            else:
                assert str(work) in line and str(shared) not in line
    assert not (work / 'scale_database').exists()
    assert not (work / 'result/SC23/20210730060000/bdyorg').exists()
    assert before == {p.relative_to(shared): p.read_bytes() for p in shared.rglob('*') if p.is_file()}


@pytest.mark.parametrize('stage', ['scale-rm_pp_ens', 'scale-rm_init_ens', 'scale-rm_ens', 'letkf'])
def test_failed_stage_retains_log_stops_and_shuts_down_owned_mps(runtime, stage):
    directory, _, _ = runtime
    result = run(runtime, FAIL_STAGE=stage)
    assert result.returncode != 0
    assert not (directory / 'results/result').read_text()
    assert (directory / 'mps').read_text() == 'start\nquit\n'
    index = ['scale-rm_pp_ens', 'scale-rm_init_ens', 'scale-rm_ens', 'letkf'].index(stage)
    assert len((directory / 'trace').read_text().splitlines()) == index + 1
    assert (directory / 'results' / (['pp', 'init', 'scale', 'letkf'][index] + '.log')).exists()


def test_missing_expanded_input_stops_before_mps(runtime):
    directory, shared, _ = runtime
    (shared / 'result/SC23/obs_radar/radar_20210730060030.dat').unlink()
    assert run(runtime).returncode != 0
    assert not (directory / 'mps').exists()


def test_matrix_and_manual_submit_use_standard_launch_allocation_without_python(tmp_path):
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    (tmp_path / 'config').symlink_to(ROOT / 'config', target_is_directory=True)
    app = tmp_path / 'programs/sharedgpu'
    app.mkdir(parents=True)
    (app / 'list.csv').write_text('system,enable,nodes,numproc_node,nthreads,elapse\nRIKYU,yes,1,1,32,0:10:00\n')
    tools = tmp_path / 'tools'
    tools.mkdir()
    for command in Path('/usr/bin').iterdir():
        if command.is_file() and not command.name.startswith(('python', 'pypy', 'pip', 'pytest')):
            (tools / command.name).symlink_to(command)
    (tools / 'sbatch').unlink(missing_ok=True)
    (tools / 'sbatch').write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$SUBMIT_TRACE"\n')
    (tools / 'sbatch').chmod(0o755)
    env = dict(os.environ, PATH=str(tools), SUBMIT_TRACE=str(tmp_path / 'submitted'),
               BK_SCHEDULER_EXTRA_ARGS_RIKYU='--account=fixture')
    matrix = subprocess.run(['bash', 'scripts/matrix_generate.sh', 'code=sharedgpu', 'system=RIKYU'],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert matrix.returncode == 0, matrix.stderr
    generated = (tmp_path / '.gitlab-ci.generated.yml').read_text()
    assert '--ntasks-per-node=1 --cpus-per-task=32 --gpus=1' in generated
    manual = subprocess.run(['bash', 'scripts/test_submit.sh', 'sharedgpu', '1'],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert manual.returncode == 0, manual.stdout + manual.stderr
    assert '--ntasks-per-node=1 --cpus-per-task=32 --gpus=1' in (tmp_path / 'submitted').read_text()


def test_shared_output_destination_is_rejected(runtime):
    directory, shared, _ = runtime
    spec = importlib.util.spec_from_file_location('prepare', APP / 'prepare-rikyu.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    work = directory / 'config-check'
    (work / 'conf').mkdir(parents=True)
    text = (f'BASENAME_ORG = "{work}/result/SC23/20210730060000/bdyorg/mean/bdyorg",\n'
            f'OBS_IN_NAME = "{work}/result/SC23/obs_radar/radar_20210730060030.dat",\n'
            f'GTOPO30_IN_DIR = "{work}/scale_database/topo/GTOPO30/Products",\n'
            f'RESTART_OUT_BASENAME = "{shared}/must-not-write",\n')
    (work / 'conf/test.conf').write_text(text)
    with pytest.raises(ValueError, match='writable'):
        module.configure(work, shared)


def test_unsupported_rank_layout_stops_before_mps(runtime):
    directory, _, env = runtime
    result = subprocess.run(['bash', str(APP / 'run.sh'), 'RIKYU', '1', '4', '1'],
                            cwd=directory, env=env, capture_output=True, text=True)
    assert result.returncode != 0 and not (directory / 'mps').exists()
