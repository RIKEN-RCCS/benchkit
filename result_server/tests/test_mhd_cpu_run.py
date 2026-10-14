"""Artifact-only MHD CPU launch and existing result extraction."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LOG = 'total step, final dt, final time: 100 0.01 3.01\nsim time [s]: 2.5\ntime/count/cell 1.0e-8\nprogram has been finished\n'
DIAG = '0 0.1 0.01 0.0012\n3.01 0.2 0.05 0.1\n'
CONFIG = 'real(8),parameter:: timemax = 3.0d0\ninteger,parameter:: nhymax = 600000\n'

def test_run_without_source_checkout(tmp_path):
    (tmp_path/'scripts').symlink_to(ROOT/'scripts', target_is_directory=True)
    shutil.copytree(ROOT/'programs/MHDTurbulence', tmp_path/'programs/MHDTurbulence')
    art = tmp_path/'artifacts'
    (art/'mhd_cpu_input').mkdir(parents=True)
    (art/'mhd_cpu_input/config.f90').write_text(CONFIG)
    (art/'mhd_cpu_input/main.f90').write_text('initial conditions fixture\n')
    exe = art/'Simulation.x'
    exe.write_text("#!/bin/bash\ncat <<'LOG'\n"+LOG+"LOG\ncat > t-prof.csv <<'DIAG'\n"+DIAG+"DIAG\n")
    exe.chmod(0o755)
    bindir = tmp_path/'bin'; bindir.mkdir()
    launcher = bindir/'srun'
    launcher.write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$LAUNCH_LOG"\nshift 4\nexec "$@"\n'); launcher.chmod(0o755)
    envfile = tmp_path/'env'; envfile.write_text('module() { :; }\n')
    env = dict(os.environ, BASH_ENV=str(envfile), PATH=str(bindir)+':'+os.environ['PATH'],LAUNCH_LOG=str(tmp_path/'launch'))
    proc = subprocess.run(['bash',str(tmp_path/'programs/MHDTurbulence/run.sh'),'Camphor3','1','96','1'],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert proc.returncode == 0, proc.stdout+proc.stderr
    assert not (tmp_path/'MHDTurbulence').exists()
    assert float((tmp_path/'results/result').read_text().split()[0].split(':')[1]) == 1.0e8
    assert 'SECTION:total time:2.5' in (tmp_path/'results/result').read_text()
    assert '-n 96 --ntasks-per-node=96 --cpus-per-task=1' in (tmp_path/'launch').read_text()
    assert (tmp_path/'results/input_info.json').is_file()
