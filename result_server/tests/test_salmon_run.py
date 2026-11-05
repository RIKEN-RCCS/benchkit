"""Use the staged SALMON restart directly and check normal iteration timing."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def inputs(path):
    (path/'restart').mkdir(parents=True)
    (path/'Si-3-3-3-tddft.nml').write_text("&parallel\n nproc_ob = 4\n/\n&tgrid\n nt = 300\n/\n")
    (path/'Si.psp8').write_text('potential')
    for name in ('info', 'occupation', 'rho_inout', 'wfn'):
        (path/'restart'/f'{name}.bin').write_text('input '+name)


@pytest.mark.parametrize('timer', ['12.5','NaN','-1','0','1e999'])
def test_rikyu_normal_run_reads_existing_restart_and_validates_timer(tmp_path,timer):
    source=tmp_path/'source';inputs(source);work=tmp_path/'workspace';work.mkdir()
    shutil.copytree(ROOT/'programs/salmon',work/'programs/salmon')
    shutil.copytree(ROOT/'scripts',work/'scripts')
    (work/'artifacts').mkdir()
    binary=work/'artifacts/salmon'
    binary.write_text('#!/bin/bash\nset -e\ncat > consumed.nml\n'
                      'test -L restart\ncat restart/wfn.bin > /dev/null\n'
                      'echo "rt iterations '+timer+' seconds per run"\n'
                      'echo "total calculation time"\n')
    binary.chmod(0o755)
    tools=tmp_path/'bin';tools.mkdir()
    launcher=tools/'mpirun';launcher.write_text('#!/bin/bash\nset -e\n'
        'test "$1" = -n; test "$2" = 4; test "$3" = --mca; test "$4" = fcoll; test "$5" = individual\n'
        'shift 5\nexport OMPI_COMM_WORLD_LOCAL_SIZE=4 OMPI_COMM_WORLD_LOCAL_RANK=0 NCUDA_GPUS=4\nexec "$@"\n')
    launcher.chmod(0o755)
    env={k:v for k,v in os.environ.items() if not k.startswith(('BK_','BASH_ENV','SALMON_'))}
    bootstrap=tmp_path/'bootstrap';bootstrap.write_text('module() { :; }; export -f module\n')
    env.update(PATH=str(tools)+os.pathsep+env['PATH'],BASH_ENV=str(bootstrap),BK_SALMON_RESTART_DIR=str(source))
    result=subprocess.run(['bash','scripts/run_benchmark.sh','programs/salmon/run.sh','RIKYU','1','4','1'],cwd=work,env=env,capture_output=True,text=True)
    assert (result.returncode==0)==(timer=='12.5'),result.stdout+result.stderr
    text=(work/'results/result').read_text()
    if timer=='12.5':
        assert 'orbital' in text and 'mixed' in text and text.count('12.5')==2
    else:assert not text
    assert (source/'restart/wfn.bin').read_text()=='input wfn'
