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


@pytest.mark.parametrize("system,threads", [("Camphor3", "14"), ("Flow2_Type1", "6"), ("Flow2_Type2", "9")])
def test_cpu_run_preserves_build_source_and_emits_observations(tmp_path, system, threads):
    import os
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    (tmp_path / 'programs').symlink_to(ROOT / 'programs', target_is_directory=True)
    repo = tmp_path / 'genesis_benchmark_input'
    work = repo / 'npt/genesis2.0beta_3.5fs/apoa1'
    inputs = repo / 'inputs/apoa1'
    work.mkdir(parents=True)
    inputs.mkdir(parents=True)
    (work / 'p8.inp').write_text('[INPUT]\npdbfile = ../../../inputs/apoa1/apoa1.pdb\n[DYNAMICS]\nnsteps = 20\n')
    for name in ['top_all27_prot_lipid.rtf', 'par_all27_prot_lipid.prm',
                 'apoa1.psf', 'apoa1.pdb', 'apoa1.rst']:
        (inputs / name).write_text(name + ' fixture\n')
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
    launch.write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$LAUNCH_LOG"\nshift '+('4' if system == 'Camphor3' else '6' if system == 'Flow2_Type2' else '2')+'\nexec "$@"\n')
    launch.chmod(0o755)
    envfile = tmp_path / 'bash-env'
    envfile.write_text('module() { :; }\n')
    env = dict(os.environ, BASH_ENV=str(envfile), PATH=str(bindir)+':'+os.environ['PATH'],
               GENESIS_INPUT_COMMIT=sha, LAUNCH_LOG=str(tmp_path / 'launch.log'))
    if system == 'Flow2_Type2':
        mpi = tmp_path / 'hpcx/ompi5'
        (mpi / 'lib').mkdir(parents=True)
        for library in ['libmpi.so', 'libopen-pal.so', 'libpmix.so']:
            (mpi / 'lib' / library).touch()
        env['OMPI_HOME'] = str(mpi)
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

    import hashlib
    import json
    records = json.loads((results / 'input_info.json').read_text())['inputs']
    files = {r['dataset_id'].removeprefix('apoa1-p8-'): r for r in records
             if 'observation_capture' in r}
    assert set(files) == {'p8.inp.sub', 'top_all27_prot_lipid.rtf',
                          'par_all27_prot_lipid.prm', 'apoa1.psf', 'apoa1.pdb', 'apoa1.rst'}
    for name, record in files.items():
        data = (work / name).read_bytes()
        capture = record['observation_capture']
        observed = capture['manifest']['files'][0]
        assert capture['collection_status'] == 'recorded'
        assert observed['sha256'] == hashlib.sha256(data).hexdigest()
        assert observed['size_bytes'] == len(data)
        assert record['result_exp'] == 'p8' and record['resolved_commit'] == sha
    assert (work / 'p8.inp.sub').read_bytes() != (work / 'p8.inp').read_bytes()
    assert files['p8.inp.sub']['observation_capture']['manifest']['files'][0]['sha256'] != hashlib.sha256((work / 'p8.inp').read_bytes()).hexdigest()

    if system == 'Flow2_Type2':
        assert '--bind-to core --map-by ppr:8:node:PE=9' in (tmp_path / 'launch.log').read_text()


def test_type2_mpi_library_selection(tmp_path):
    import os
    import shutil
    gcc = shutil.which('gcc')
    if not gcc:
        pytest.skip('gcc required for dynamic loader reproduction')
    mpi = tmp_path / 'hpcx/ompi5'
    lib = mpi / 'lib'
    lib.mkdir(parents=True)
    old = tmp_path / 'old'
    old.mkdir()
    def compile_source(name, source, *args):
        path = tmp_path / (name + '.c')
        path.write_text(source)
        subprocess.run([gcc, str(path), *args], check=True, capture_output=True)
    compile_source('pmix', 'int pmix_framework_names = 7;', '-shared', '-fPIC',
                   '-Wl,-soname,libpmix.so.2', '-o', str(lib / 'libpmix.so.2'))
    (lib / 'libpmix.so').symlink_to('libpmix.so.2')
    compile_source('oldpmix', 'int old_pmix = 1;', '-shared', '-fPIC',
                   '-Wl,-soname,libpmix.so.2', '-o', str(old / 'libpmix.so.2'))
    compile_source('pal', 'extern int pmix_framework_names; int check(void) {return pmix_framework_names;}',
                   '-shared', '-fPIC', '-L'+str(lib), '-lpmix', '-Wl,--enable-new-dtags,-rpath,$ORIGIN',
                   '-o', str(lib / 'libopen-pal.so'))
    (lib / 'libmpi.so').touch()
    exe = tmp_path / 'probe'
    compile_source('main', 'extern int check(void); int main(void) {return check() != 7;}',
                   '-L'+str(lib), '-lopen-pal', '-Wl,--enable-new-dtags,-rpath,'+str(lib),
                   '-Wl,-rpath-link,'+str(lib), '-o', str(exe))
    env = dict(os.environ, OMPI_HOME=str(mpi), LD_LIBRARY_PATH=str(old))
    failed = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
    assert failed.returncode != 0 and 'pmix_framework_names' in failed.stderr
    helper = ROOT / 'programs/genesis/flow2_type2_env.sh'
    fixed = subprocess.run(['bash', '-eu', '-c', 'source "$1"; exec "$2"',
                            '_', str(helper), str(exe)], env=env, capture_output=True, text=True)
    assert fixed.returncode == 0, fixed.stderr
    (lib / 'libpmix.so').unlink()
    missing = subprocess.run(['bash', '-eu', str(helper)], env=env, capture_output=True, text=True)
    assert missing.returncode != 0 and 'missing HPC-X library' in missing.stderr


@pytest.mark.parametrize("mode,text,passed", [
    ("makefile", "FCFLAGS = -O2 -mp -Mflushz\n", True),
    ("makefile", "FCFLAGS = -O2 -Mflushz\n", False),
    ("makefile", "CFLAGS = -O2 -mp -Mflushz\n", False),
    ("compile", "mpif90 -O2 -mp -Mflushz -c main.f90\n", True),
    ("compile", "mpif90 -O3 -c main.f90\n", False),
    ("compile", "mpicc -O2 -mp -Mflushz -c main.c\n", False),
])
def test_type2_rejects_lost_fortran_options(tmp_path, mode, text, passed):
    evidence = tmp_path / "evidence"
    evidence.write_text(text)
    command = ["bash", str(ROOT / "programs/genesis/verify_fortran_flags.sh")]
    if mode == "compile":
        command.append("--compile-log")
    command += ["-O2 -mp -Mflushz", str(evidence)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert (result.returncode == 0) == passed, result.stdout + result.stderr
