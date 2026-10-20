"""Preserve optional NVTX evidence and scope the actual NCU command safely."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'scripts/profiling'
LABEL = 'sbdiag.h:Run:461 : Davidson [coarse]'


def generate(tmp_path, rows, *extra):
    nvtx = tmp_path / 'nvtx.csv'
    with nvtx.open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['NVTX Range', 'Style', 'PID', 'TID', 'NVTX Inst', 'Kern Inst',
                    'Total Time (ns)', 'Kernel Name'])
        w.writerows(rows)
    plan = tmp_path / 'plan.json'
    discovery = tmp_path / 'discovery.json'
    result = subprocess.run([sys.executable, str(TOOLS / 'generate_ncu_plan.py'),
        '--nsys-csv', str(ROOT / 'scripts/tests/fixtures/nsys_cuda_gpu_kern_sum.csv'),
        '--nvtx-csv', str(nvtx), '--out-plan', str(plan), '--out-discovery', str(discovery),
        '--top-k', '0', *extra], capture_output=True, text=True)
    return result, plan, discovery


def sample(label=LABEL, pid='100', tid='101', style='PushPop', name='same_kernel(float*)', count=4, duration=40):
    return [label, style, pid, tid, 2, count, duration, name]


def test_unselected_nvtx_preserves_old_plan_and_evidence(tmp_path):
    baseline = subprocess.run([sys.executable, str(TOOLS / 'generate_ncu_plan.py'),
        '--nsys-csv', str(ROOT / 'scripts/tests/fixtures/nsys_cuda_gpu_kern_sum.csv'),
        '--top-k', '0'], capture_output=True, text=True, check=True)
    old_profiles = json.loads(baseline.stdout)['profiles']
    kernel = old_profiles[0]['kernel_name']
    result, plan, discovery = generate(tmp_path, [sample(name=kernel), sample('nested', name=kernel)])
    assert result.returncode == 0, result.stderr
    data = json.loads(plan.read_text())
    assert all('nvtx' not in p for p in data['profiles'])
    assert data['source']['report'] == 'cuda_gpu_kern_sum'
    rendered = subprocess.run([sys.executable, str(TOOLS / 'render_ncu_plan_commands.py'),
        '--plan', str(plan), '--format', 'json', '--', './diag'],
        capture_output=True, text=True, check=True)
    assert all(c['env']['BK_PROFILER_NCU_NVTX_INCLUDE'] == ''
               for c in json.loads(rendered.stdout)['commands'])
    evidence = json.loads(discovery.read_text())['nvtx']
    assert len(evidence['associations']) == 2
    assert evidence['selected_scope'] is None
    assert len(data['profiles'][0]['selection']['nvtx_associations']) == 2
    # Nested evidence does not alter any global selection counts or durations.
    for profile in data['profiles']:
        profile['selection'].pop('nvtx_associations')
    assert data['profiles'] == old_profiles



def test_scope_excludes_same_kernel_elsewhere_and_does_not_guess_section(tmp_path):
    result, plan, _ = generate(tmp_path, [sample(), sample('post Davidson', count=50, duration=500)],
                               '--nvtx-range', LABEL)
    assert result.returncode == 0, result.stderr
    p = json.loads(plan.read_text())['profiles'][0]
    assert p['selection']['source_launches'] == 4
    assert p['selection']['source_gpu_duration_ns'] == 40
    assert p['launch_count'] + p['launch_skip'] == 4
    assert p['nvtx']['range'] == LABEL
    assert p['section'] is None
    result = subprocess.run([sys.executable, str(TOOLS / 'render_ncu_plan_commands.py'),
                             '--plan', str(plan), '--format', 'json', '--', './diag'],
                            capture_output=True, text=True, check=True)
    record = json.loads(result.stdout)['commands'][0]
    assert record['env']['BK_PROFILER_NCU_NVTX_INCLUDE'] == LABEL.replace('[', r'\[').replace(']', r'\]') + '/'
    assert record['bk_profiler_args'][-3:] == ['--nvtx', '--nvtx-include', record['env']['BK_PROFILER_NCU_NVTX_INCLUDE']]
    result = subprocess.run([sys.executable, str(TOOLS / 'iter_ncu_plan_profiles.py'),
                            '--plan', str(plan), '--metadata', p['name']],
                           capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['nvtx'] == p['nvtx']


@pytest.mark.parametrize('rows,extra', [
    ([sample()], ['--nvtx-range', 'missing']),
    ([sample(), sample(pid='200')], ['--nvtx-range', LABEL]),
    ([sample(), sample(tid='102')], ['--nvtx-range', LABEL]),
    ([sample(), sample()], ['--nvtx-range', LABEL]),
    ([sample(style='unknown')], []),
    ([sample(duration='NaN')], []),
    ([sample(count=0)], []),
])
def test_bad_or_ambiguous_scope_fails_without_unscoped_fallback(tmp_path, rows, extra):
    result, plan, _ = generate(tmp_path, rows, *extra)
    assert result.returncode != 0
    assert not plan.exists()


def test_explicit_process_thread_and_start_end(tmp_path):
    result, plan, _ = generate(tmp_path, [sample(style='StartEnd'), sample(pid='200')],
        '--nvtx-range', LABEL, '--nvtx-process-id', '100', '--nvtx-thread-id', '101')
    assert result.returncode == 0, result.stderr
    p = json.loads(plan.read_text())['profiles'][0]
    result = subprocess.run([sys.executable, str(TOOLS / 'iter_ncu_plan_profiles.py'),
                            '--plan', str(plan), '--nvtx-args', p['name']],
                           capture_output=True, text=True, check=True)
    assert not result.stdout.splitlines()[-1].endswith('/')


def test_actual_acquisition_keeps_space_and_shell_characters_in_one_argument(tmp_path):
    label = 'Davidson $(touch NEVER_EXECUTE) [coarse]'
    result, plan, _ = generate(tmp_path, [sample(label)], '--nvtx-range', label)
    assert result.returncode == 0, result.stderr
    p = json.loads(plan.read_text())['profiles'][0]
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    ncu = bindir / 'ncu'
    ncu.write_text('#!' + sys.executable + '''
import json, os, sys
from pathlib import Path
if '--import' not in sys.argv:
    Path(os.environ['ARGV']).write_text(json.dumps(sys.argv[1:]))
    Path(sys.argv[sys.argv.index('-o')+1]+'.ncu-rep').write_text('fixture')
print('metric,value')
''')
    ncu.chmod(0o755)
    work = tmp_path / 'work'
    work.mkdir()
    shell = '''source scripts/profiling/acquisition.sh
bk_require_ncu_plan_python() { :; }
_bk_profile_workspace() { printf '%s\\n' "$WORK"; }
bk_ncu_window_level_args() { printf '%s\\n' --set basic; }
bk_profile_slug() { printf '%s' "$1"; }
bk_profile_execute() { while [ "$1" != -- ]; do shift; done; shift; "$@"; }
bk_profiler_find_ncu_report() { printf '%s/profile.ncu-rep' "$1"; }
bk_bool_enabled() { return 1; }
bk_profiler_write_meta() { printf '{}' > "$1/meta.json"; }
bk_write_gpu_kernel_profile_metadata() { printf '%s' "$9" > "$1"; }
_bk_profile_register() { :; }
bk_acquire_ncu --profile-name "$NAME" --section unrelated --kernel-regex same_kernel --plan "$PLAN" -- true
'''
    env = dict(os.environ, PATH=str(bindir)+':'+os.environ['PATH'], WORK=str(work),
               BK_BENCHKIT_ROOT=str(ROOT), PYTHON_BIN=sys.executable, NAME=p['name'],
               PLAN=str(plan), ARGV=str(tmp_path / 'argv.json'))
    r = subprocess.run(['bash', '-euc', shell], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    argv = json.loads((tmp_path / 'argv.json').read_text())
    assert argv[argv.index('--nvtx-include')+1] == label.replace('[', r'\[').replace(']', r'\]')+'/'
    assert not (ROOT / 'NEVER_EXECUTE').exists()
    metadata = json.loads((work / 'profile.metadata.json').read_text())
    assert metadata['nvtx']['range'] == label
    assert metadata['section'] == ''

    # The dry-run renderer's dedicated scalar also reaches generic bk_profiler
    # without the word-splitting used for legacy extra flags.
    env['BK_PROFILER_NCU_NVTX_INCLUDE'] = argv[argv.index('--nvtx-include')+1]
    generic = 'source scripts/bk_functions.sh; bk_run_context --results-dir "$WORK/generic-results" --exp nvtx; bk_profiler ncu --level single --archive "$WORK/generic.tgz" --raw-dir "$WORK/generic-raw" -- true'
    r = subprocess.run(['bash', '-euc', generic], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    generic_argv = json.loads((tmp_path / 'argv.json').read_text())
    assert generic_argv[generic_argv.index('--nvtx-include')+1] == env['BK_PROFILER_NCU_NVTX_INCLUDE']


@pytest.mark.parametrize('raw_name', [LABEL, ':' + LABEL])
def test_sqlite_resolves_display_label_and_preserves_literal_name(tmp_path, raw_name):
    import sqlite3
    db = tmp_path / 'discovery.sqlite'
    with sqlite3.connect(db) as connection:
        connection.executescript('CREATE TABLE StringIds(id INTEGER, value TEXT); '
                                 'CREATE TABLE NVTX_EVENTS(text TEXT, textId INTEGER, domainId INTEGER);')
        connection.execute('INSERT INTO StringIds VALUES(1, ?)', (raw_name,))
        connection.execute('INSERT INTO NVTX_EVENTS VALUES(NULL, 1, 0)')
    display = ':' + raw_name
    result, plan, discovery = generate(tmp_path, [sample(display)],
        '--nvtx-range', display, '--nvtx-sqlite', str(db))
    assert result.returncode == 0, result.stderr
    scope = json.loads(plan.read_text())['profiles'][0]['nvtx']
    assert scope['range'] == raw_name
    assert scope['display_range'] == display
    assert scope['domain'] == 'default'
    assert json.loads(discovery.read_text())['nvtx']['associations'][0]['range'] == display
    assert json.loads(discovery.read_text())['nvtx']['selected_scope'] == scope
    result = subprocess.run([sys.executable, str(TOOLS / 'render_ncu_plan_commands.py'),
        '--plan', str(plan), '--format', 'json', '--', './diag'],
        capture_output=True, text=True, check=True)
    record = json.loads(result.stdout)['commands'][0]
    assert record['env']['BK_PROFILER_NCU_NVTX_INCLUDE'] == raw_name.replace('[', r'\[').replace(']', r'\]') + '/'
    result = subprocess.run([sys.executable, str(TOOLS / 'iter_ncu_plan_profiles.py'),
        '--plan', str(plan), '--metadata', json.loads(plan.read_text())['profiles'][0]['name']],
        capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['nvtx'] == scope


@pytest.mark.parametrize('domain,name', [(1, LABEL), (0, 'other range')])
def test_sqlite_unconfirmed_or_named_domain_fails_closed(tmp_path, domain, name):
    import sqlite3
    db = tmp_path / 'discovery.sqlite'
    with sqlite3.connect(db) as connection:
        connection.executescript('CREATE TABLE StringIds(id INTEGER, value TEXT); '
                                 'CREATE TABLE NVTX_EVENTS(text TEXT, textId INTEGER, domainId INTEGER);')
        connection.execute('INSERT INTO NVTX_EVENTS VALUES(?, NULL, ?)', (name, domain))
    result, plan, _ = generate(tmp_path, [sample(':' + LABEL)],
        '--nvtx-range', ':' + LABEL, '--nvtx-sqlite', str(db))
    assert result.returncode != 0
    assert not plan.exists()


def test_sqlite_missing_is_not_created_or_ignored(tmp_path):
    db = tmp_path / 'missing.sqlite'
    result, plan, _ = generate(tmp_path, [sample(':' + LABEL)],
        '--nvtx-range', ':' + LABEL, '--nvtx-sqlite', str(db))
    assert result.returncode != 0
    assert not plan.exists()
    assert not db.exists()
