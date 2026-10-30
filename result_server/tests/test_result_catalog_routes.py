"""Synthetic receipt and page checks, with no live services or credentials."""

import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_usage_route import app, client, tmp_dirs, _login_session
from test_support import build_api_route_app
from utils.result_catalog import CatalogUnavailable, ResultCatalog


@pytest.fixture
def index(app, tmp_dirs, tmp_path):
    store = tmp_path / 'catalog'
    store.mkdir(mode=0o700)
    catalog = ResultCatalog(store / 'index', tmp_dirs[0])
    catalog.initialize()
    for name, data in [('public.json', dict(system='PublicSystem', code='app', Exp='E')),
                       ('secret.json', dict(system='HiddenSystem', code='secret-app', Exp='Secret', confidential=['team']))]:
        (Path(tmp_dirs[0]) / name).write_text(json.dumps(data))
    catalog.rebuild()
    app.config['RESULT_CATALOG_PATH'] = str(catalog.path)
    return catalog


@pytest.mark.parametrize('url', ['/results/', '/results/?candidates=1&code=app',
                                  '/results/?candidates=1&catalog_page=2'])
def test_candidate_only_pages_never_read_result_json(client, index, monkeypatch, url):
    def denied(*args, **kwargs):
        raise AssertionError('Page queried Result JSON or repository definitions')
    monkeypatch.setattr(os, 'listdir', denied)
    monkeypatch.setattr('routes.results_list_routes.load_results_table', denied)
    monkeypatch.setattr('routes.results_list_routes.definition_options', denied)
    response = client.get(url)
    assert response.status_code == 200
    assert 'Available Results' in response.text and 'PublicSystem' in response.text
    assert 'HiddenSystem' not in response.text and 'secret-app' not in response.text
    assert '<table id="resultsTable"' not in response.text


def test_public_route_stays_public_for_admin(client, index):
    _login_session(client, 'admin@example.com', ['admin'])
    response = client.get('/results/')
    assert 'HiddenSystem' not in response.text
    response = client.get('/results/confidential')
    assert 'HiddenSystem' in response.text
    assert 'no-store' in response.headers['Cache-Control']


def test_current_affiliations_are_not_cached(client, index, app):
    from test_support import StaticAffiliationUserStore
    app.config['USER_STORE'] = StaticAffiliationUserStore({'user@example.com': ['team']})
    _login_session(client, 'user@example.com', ['team'])
    assert 'HiddenSystem' in client.get('/results/confidential').text
    app.config['USER_STORE'] = StaticAffiliationUserStore({'user@example.com': ['other']})
    assert 'HiddenSystem' not in client.get('/results/confidential').text


def select_options(html):
    from html.parser import HTMLParser
    class Options(HTMLParser):
        def __init__(self):
            super().__init__()
            self.controls = {}
            self.current = None
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'select':
                self.current = attrs.get('name')
                self.controls[self.current] = []
            elif tag == 'option' and self.current:
                self.controls[self.current].append(attrs)
        def handle_endtag(self, tag):
            if tag == 'select':
                self.current = None
    parser = Options()
    parser.feed(html)
    return parser.controls


def test_selected_candidate_can_be_changed_or_cleared_without_typing(client, index):
    index.replace('another.json', dict(system='OtherSystem', code='app', Exp='E'), lambda: None)
    response = client.get('/results/?candidates=1&system=PublicSystem&code=app&exp=E')
    options = select_options(response.text)
    for name in ('system', 'code', 'exp'):
        assert options[name][0]['value'] == ''
        assert sum('selected' in item for item in options[name]) == 1
        assert '<input name="' + name + '"' not in response.text
    assert {item['value'] for item in options['system']} == {'', 'PublicSystem', 'OtherSystem'}
    assert 'HiddenSystem' not in response.text
    assert 'name="candidates" value="1"' in response.text
    cleared = client.get('/results/?candidates=1&system=&code=&exp=')
    assert all('selected' in select_options(cleared.text)[name][0] for name in ('system', 'code', 'exp'))


def test_unknown_current_candidate_is_preserved_without_claiming_a_count(client, index):
    response = client.get('/results/?candidates=1&system=Unlisted&code=Unknown&exp=Other')
    options = select_options(response.text)
    for name, value in [('system', 'Unlisted'), ('code', 'Unknown'), ('exp', 'Other')]:
        assert [item['value'] for item in options[name] if 'selected' in item] == [value]
        assert options[name][0]['value'] == ''


def test_auth_required_before_reading_catalog(client, index, monkeypatch):
    monkeypatch.setattr(ResultCatalog, 'candidates', lambda *a, **kw: pytest.fail('Unauthenticated read'))
    response = client.get('/results/confidential')
    assert 'Authentication required' in response.text and 'HiddenSystem' not in response.text


def test_unavailable_catalog_is_not_zero_and_does_not_scan(client, index, monkeypatch):
    with index._connect() as conn:
        conn.execute('UPDATE catalog_state SET ready=0')
        conn.commit()
    monkeypatch.setattr(os, 'listdir', lambda *a: pytest.fail('Unexpected scan'))
    response = client.get('/results/')
    assert response.status_code == 200
    assert 'candidates are unavailable' in response.text
    assert 'Available Results' not in response.text and 'HiddenSystem' not in response.text


def test_html_escaped_and_view_preserves_exact_tuple(client, index):
    data = {'system': '<script>x</script>', 'code': 'Unknown App', 'Exp': 'E & F'}
    index.replace('odd.json', data, lambda: None)
    response = client.get('/results/')
    assert '<script>x</script>' not in response.text
    assert '&lt;script&gt;x&lt;/script&gt;' in response.text
    from urllib.parse import parse_qs, urlsplit
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                self.links.append(dict(attrs).get('href', ''))
    links = Links()
    links.feed(response.text)
    selected = [parse_qs(urlsplit(url).query) for url in links.links if 'Unknown+App' in url]
    assert selected and selected[0]['system'] == [data['system']]
    assert selected[0]['exp'] == ['E & F'] and selected[0]['search'] == ['1']


def receipt_app(tmp_dirs, path):
    app = build_api_route_app(received_dir=tmp_dirs[0], received_padata_dir=tmp_dirs[1],
                              received_estimation_artifacts_dir=tmp_dirs[2] if len(tmp_dirs) > 3 else tmp_dirs[1],
                              estimated_dir=tmp_dirs[-1])
    app.config.update(INGEST_KEYS={'synthetic-key': 'test-runner'}, RESULT_CATALOG_PATH=str(path))
    return app


def test_receipt_publishes_catalog_and_estimate_does_not(tmp_dirs, index):
    client = receipt_app(tmp_dirs, index.path).test_client()
    headers = {'X-API-Key': 'synthetic-key'}
    response = client.post('/api/ingest/result', json=dict(system='NewSystem', code='Undefined', Exp='E'), headers=headers)
    assert response.status_code == 200
    assert index.candidates(system='NewSystem')['total'] == 1
    assert 'payload' not in response.json
    response = client.post('/api/ingest/estimate', json={'code': 'Undefined'}, headers=headers)
    assert response.status_code == 200
    assert index.candidates(system='NewSystem')['total'] == 1


def test_same_saved_file_replacement_is_idempotent(tmp_dirs, index, monkeypatch):
    import routes.api as api
    from datetime import datetime
    class FixedTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1)
    monkeypatch.setattr(api, 'datetime', FixedTime)
    app = receipt_app(tmp_dirs, index.path)
    identifier = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    with app.test_request_context():
        for _ in range(2):
            api.save_json_file(b'{"system":"Once","code":"app","Exp":"E"}',
                               'result', tmp_dirs[0], given_uuid=identifier)
    assert index.candidates(system='Once')['total'] == 1
    assert len(list(Path(tmp_dirs[0]).glob('result_*.json'))) == 1


def test_catalog_failure_before_receipt_does_not_write_result(tmp_dirs, index):
    client = receipt_app(tmp_dirs, index.path.with_name('not-initialized')).test_client()
    before = sorted(Path(tmp_dirs[0]).iterdir())
    response = client.post('/api/ingest/result', json={'code': 'Undefined'}, headers={'X-API-Key': 'synthetic-key'})
    assert response.status_code == 503
    assert sorted(Path(tmp_dirs[0]).iterdir()) == before


def test_failed_publication_after_json_leaves_catalog_unavailable(tmp_dirs, index, monkeypatch):
    def fail(*args):
        raise OSError('Synthetic publication failure')
    monkeypatch.setattr(ResultCatalog, '_put', fail)
    client = receipt_app(tmp_dirs, index.path).test_client()
    response = client.post('/api/ingest/result', json={'code': 'Undefined'}, headers={'X-API-Key': 'synthetic-key'})
    assert response.status_code == 503
    assert len(list(Path(tmp_dirs[0]).glob('result_*.json'))) == 1
    with pytest.raises(CatalogUnavailable):
        index.candidates()
