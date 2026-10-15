"""NCU discovery rejects unusable Python before profiler work begins."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('interpreter', ['missing', 'old', 'broken'])
@pytest.mark.parametrize('csv_input', [False, True])
def test_discovery_checks_python_before_workspace_or_collection(tmp_path, interpreter, csv_input):
    python_bin = tmp_path / 'python'
    if interpreter != 'missing':
        # Exercise actual preflight code with an old-version or broken-stdlib proxy.
        prefix = ('import sys; sys.version_info=(3, 6); ' if interpreter == 'old' else
                  'import builtins; original=builtins.__import__; '
                  'builtins.__import__=lambda name,*a,**k: original("nonexistent_ncu_stdlib") if name=="dataclasses" else original(name,*a,**k); ')
        python_bin.write_text('#!' + sys.executable + '\nimport sys\nexec(' + repr(prefix) + '+sys.argv[2])\n')
        python_bin.chmod(0o755)
    marker = tmp_path / 'workspace'
    command = '''source scripts/bk_functions.sh
_bk_profile_workspace() { touch "$MARKER"; return 1; }
bk_discover_ncu_plan "$@"
'''
    args = ['--csv', str(tmp_path / 'summary.csv')] if csv_input else ['--', 'unused-application']
    result = subprocess.run(['bash', '-c', command, 'test', *args], cwd=ROOT,
                            env=dict(os.environ, PYTHON_BIN=str(python_bin), MARKER=str(marker)),
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Python 3.7+' in result.stderr
    assert not marker.exists()


def test_selected_supported_python_and_no_source_time_requirement():
    result = subprocess.run(['bash', '-c', 'source scripts/bk_functions.sh; bk_require_ncu_plan_python'],
                            cwd=ROOT, env=dict(os.environ, PYTHON_BIN=sys.executable),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(['bash', '-c', 'source scripts/bk_functions.sh'], cwd=ROOT,
                            env=dict(os.environ, PYTHON_BIN='/nonexistent/ncu-python'),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
