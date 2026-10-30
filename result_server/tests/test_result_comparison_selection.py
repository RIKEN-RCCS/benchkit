"""Cross-query comparison selection does not change comparison authorization."""

from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_usage_route import app, client, tmp_dirs, _login_session, _write_result
from test_support import StaticAffiliationUserStore


def scope(response):
    return re.search(r'data-scope="([a-f0-9]+)"', response.text).group(1)


def test_selection_panel_exists_before_search_and_scope_ignores_filters(client):
    first = client.get('/results/')
    second = client.get('/results/?candidates=1&system=Another')
    assert scope(first) == scope(second)
    assert 'id="resultComparison"' in first.text
    assert 'result_comparison_selection.js' in first.text
    assert '<table id="resultsTable"' not in first.text


def test_scope_is_bound_to_login_visibility_and_current_affiliations(client, app):
    public = scope(client.get('/results/'))
    _login_session(client, 'user@example.com', ['dev'])
    private = scope(client.get('/results/confidential'))
    assert public != private
    app.config['USER_STORE'] = StaticAffiliationUserStore({'user@example.com': ['changed']})
    assert scope(client.get('/results/confidential')) != private
    assert 'user@example.com' not in client.get('/results/confidential').text.split('data-scope=')[1].split('>')[0]
    with client.session_transaction() as session:
        session.clear()
    assert scope(client.get('/results/')) != public
    assert 'id="resultComparison"' not in client.get('/results/confidential').text


def test_existing_compare_rechecks_private_missing_and_unsafe_files(client, tmp_dirs):
    files = ['result_20260401_000000_a.json', 'result_20260402_000000_b.json', 'result_20260403_000000_c.json']
    for index, filename in enumerate(files):
        payload = dict(system='A' if index == 0 else 'B', code='one' if index == 0 else 'two',
                       Exp='E', FOM=index+1, FOM_unit='s')
        if index == 2:
            payload['confidential'] = ['private-team']
        _write_result(tmp_dirs[0], filename, payload)
    response = client.get('/results/compare', query_string={'files': ','.join(files[:2])})
    assert response.status_code == 200
    assert client.get('/results/compare', query_string={'files': ','.join(files[1:])}).status_code == 403
    assert client.get('/results/compare', query_string={'files': files[0] + ',missing.json'}).status_code == 404
    assert client.get('/results/compare', query_string={'files': files[0] + ',../private.json'}).status_code in (403, 404)


def test_browser_selection_logic():
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the browser logic test')
    script = Path(__file__).with_suffix('.js')
    result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
