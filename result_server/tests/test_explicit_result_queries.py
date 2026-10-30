"""Initial query screens do not walk result directories or aggregate data."""

import csv
import io
import os
from datetime import date
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from werkzeug.datastructures import MultiDict

from test_usage_route import app, client, tmp_dirs, _login_session, _write_result
from utils.report_selection import usage_selection


def admin(client):
    _login_session(client, 'admin@example.com', ['admin'])


@pytest.mark.parametrize('path', ['/results/', '/results/confidential', '/results/usage'])
def test_initial_view_never_scans_results_or_starts_a_report(client, tmp_dirs, monkeypatch, path):
    admin(client)
    original = os.listdir
    def guarded(directory):
        assert str(directory) not in tmp_dirs, 'Initial view scanned stored records'
        return original(directory)
    monkeypatch.setattr(os, 'listdir', guarded)
    def denied(*args, **kwargs):
        raise AssertionError('Initial view performed a query')
    monkeypatch.setattr('routes.results_list_routes.load_results_table', denied)
    monkeypatch.setattr('routes.results_usage_routes.build_usage_report_context', denied)
    response = client.get(path)
    assert response.status_code == 200
    assert 'name="run"' in response.text if path.endswith('usage') else 'name="search"' in response.text
    assert '<table id="resultsTable"' not in response.text
    assert 'No usage data is available' not in response.text


@pytest.mark.parametrize('query', ['search=1', 'code=demoapp', 'page=1&per_page=50'])
def test_explicit_and_legacy_search_urls_preserve_visibility(client, tmp_dirs, query):
    public = 'result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json'
    private = 'result_20260402_123456_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json'
    for name, extra in ((public, {}), (private, {'confidential': ['restricted']})):
        _write_result(tmp_dirs[0], name, dict(code='demoapp', system='DemoSystem', Exp='CASE0', FOM=1, **extra))
    response = client.get('/results/?' + query)
    assert response.status_code == 200 and public in response.text and private not in response.text
    _login_session(client, 'user@example.com', ['dev'])
    response = client.get('/results/confidential?' + query)
    assert public in response.text and private not in response.text
    admin(client)
    response = client.get('/results/confidential?' + query)
    assert public in response.text and private in response.text
    assert 'name="search" value="1"' in response.text


def test_empty_form_fields_do_not_become_empty_string_filters(client, tmp_dirs):
    _write_result(tmp_dirs[0], 'result_20260401_000000_a.json',
                  dict(code='demoapp', system='DemoSystem', Exp='CASE0', FOM=1))
    response = client.get('/results/?search=1&system=&code=&exp=&per_page=50')
    assert response.status_code == 200 and 'result_20260401_000000_a.json' in response.text
    assert 'onchange="applyServerFilter()"' not in response.text


@pytest.mark.parametrize('report, builder', [
    ('node_hours', 'aggregate_node_hours'), ('profiles', 'build_profile_usage_overview'),
    ('performance', 'build_performance_telemetry'), ('evidence', 'build_evidence_snapshot'),
    ('configuration', 'build_site_diagnostics'),
])
def test_only_the_selected_report_is_built(client, monkeypatch, report, builder):
    import utils.usage_report_view as view
    names = ['aggregate_node_hours', 'build_profile_usage_overview', 'build_performance_telemetry',
             'build_evidence_snapshot', 'build_site_diagnostics']
    called = []
    real = getattr(view, builder)
    def selected(*args, **kwargs):
        called.append(builder)
        return real(*args, **kwargs)
    def denied(*args, **kwargs):
        raise AssertionError('An unrelated report was calculated')
    for name in names:
        monkeypatch.setattr(view, name, selected if name == builder else denied)
    admin(client)
    response = client.get('/results/usage?run=1&report=' + report + '&fiscal_year=2026')
    assert response.status_code == 200
    assert called == [builder]


def seed_records(directory):
    for name, code, system, fom in [
        ('result_20260401_000000_a.json', 'demoapp', 'DemoSystem', 1),
        ('result_20260501_000000_b.json', 'demoapp', 'DemoSystem', 2),
        ('result_20260401_000000_c.json', 'otherapp', 'DemoSystem', 3),
        ('result_20260401_000000_d.json', 'demoapp', 'OtherSystem', 4),
        ('result_20270401_000000_e.json', 'demoapp', 'DemoSystem', 5),
    ]:
        _write_result(directory, name, dict(code=code, system=system, Exp='CASE0', FOM=fom,
            node_count=1, pipeline_timing={'run_time': fom}, execution_mode='run'))


@pytest.mark.parametrize('report', ['node_hours', 'performance', 'evidence'])
def test_selected_targets_and_month_are_applied_to_report(client, tmp_dirs, report):
    seed_records(tmp_dirs[0])
    admin(client)
    response = client.get('/results/usage', query_string={
        'run': '1', 'report': report, 'fiscal_year': '2026', 'period_type': 'monthly',
        'period_filter': '2026-04', 'code': 'demoapp', 'system': 'DemoSystem',
    })
    assert response.status_code == 200
    # Targets that only occur outside the requested scope must not appear as report rows.
    assert 'otherapp' not in response.text and 'OtherSystem' not in response.text
    if report == 'evidence':
        assert 'result_20260401_000000_a.json' in response.text
        assert 'result_20260501_000000_b.json' not in response.text
        assert 'result_20270401_000000_e.json' not in response.text
        assert 'period_filter=2026-04' in response.text


def test_csv_matches_the_selected_target_and_period(client, tmp_dirs):
    seed_records(tmp_dirs[0])
    admin(client)
    response = client.get('/results/usage/evidence-snapshot.csv', query_string={
        'fiscal_year': '2026', 'period_type': 'monthly', 'period_filter': '2026-04',
        'code': 'demoapp', 'system': 'DemoSystem'})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1 and rows[0]['latest_result_time'] == '2026-04-01 00:00:00'
    assert 'otherapp' not in response.text and 'OtherSystem' not in response.text


@pytest.mark.parametrize('query', [
    {'run': '1', 'report': 'bad'}, {'run': '1', 'fiscal_year': '9999'},
    {'run': '1', 'period_type': 'monthly', 'fiscal_year': '2026', 'period_filter': '2027-04'},
    {'run': '1', 'period_type': 'monthly', 'period_filter': 'invalid'},
    {'run': '1', 'period_type': 'semi_annual', 'period_filter': 'H3'},
])
def test_invalid_report_selection_does_not_start_a_report(client, monkeypatch, query):
    admin(client)
    def denied(*args, **kwargs):
        raise AssertionError('Invalid query started a report')
    monkeypatch.setattr('routes.results_usage_routes.build_usage_report_context', denied)
    assert client.get('/results/usage', query_string=query).status_code == 400


def test_fiscal_half_bounds():
    selection = usage_selection(MultiDict(), 2026, 'semi_annual', 'H2')
    assert selection['since'] == date(2026, 10, 1)
    assert selection['until'] == date(2027, 4, 1)


def test_filtered_list_builds_only_one_page_of_rows(tmp_path, monkeypatch):
    import utils.results_loader as loader
    for index in range(65):
        _write_result(str(tmp_path), f'result_20260401_000000_{index:03}.json',
                      dict(code='demoapp', system='DemoSystem', Exp='CASE0', FOM=1))
    built = []
    def row(filename, *args, **kwargs):
        built.append(filename)
        return {'filename': filename}
    monkeypatch.setattr(loader, 'build_result_table_row', row)
    rows, _, pagination = loader.load_results_table(str(tmp_path), filter_code='demoapp', per_page=50)
    assert len(rows) == len(built) == 50
    assert pagination['total'] == 65


def test_profile_report_scopes_received_results(client, app, tmp_dirs, tmp_path):
    from test_execution_profiles import _profile
    from utils.execution_profiles import ExecutionProfileStore
    db = tmp_path / 'synthetic-profiles.sqlite3'
    store = ExecutionProfileStore(str(db))
    store.upsert_profile(_profile(system=['DemoSystem']), actor='synthetic')
    app.config['EXECUTION_PROFILE_DB_PATH'] = str(db)
    seed_records(tmp_dirs[0])
    admin(client)
    response = client.get('/results/usage', query_string={
        'run': '1', 'report': 'profiles', 'fiscal_year': '2026', 'period_type': 'monthly',
        'period_filter': '2026-04', 'code': 'demoapp', 'system': 'DemoSystem'})
    assert response.status_code == 200
    assert 'result_20260401_000000_a.json' in response.text
    assert 'result_20260501_000000_b.json' not in response.text


def test_evidence_does_not_add_estimate_targets_outside_selection(client, tmp_dirs):
    seed_records(tmp_dirs[0])
    _write_result(tmp_dirs[1], 'estimate_20260402_000000_a.json', {
        'code': 'demoapp', 'exp': 'CASE0', 'current_system': {'system': 'DemoSystem'},
        'future_system': {'system': 'OtherSystem'}, 'applicability': {'status': 'applicable'}})
    admin(client)
    response = client.get('/results/usage/evidence-snapshot.csv', query_string={
        'fiscal_year': '2026', 'code': 'demoapp', 'system': 'DemoSystem'})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows and all(row['system'] == 'DemoSystem' for row in rows)


def test_list_paging_keeps_explicit_search_and_targets(client, tmp_dirs):
    for index in range(65):
        _write_result(tmp_dirs[0], f'result_20260401_000000_{index:03}.json',
                      dict(code='demoapp', system='DemoSystem', Exp='CASE0', FOM=1))
    response = client.get('/results/?search=1&code=demoapp&system=DemoSystem&exp=CASE0&per_page=50')
    assert response.status_code == 200
    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.queries = []
        def handle_starttag(self, tag, attrs):
            href = dict(attrs).get('href')
            if tag == 'a' and href:
                self.queries.append(parse_qs(urlsplit(href).query))
    links = Links()
    links.feed(response.text)
    assert {'page': ['2'], 'per_page': ['50'], 'search': ['1'], 'system': ['DemoSystem'],
            'code': ['demoapp'], 'exp': ['CASE0']} in links.queries
    assert 'name="search" value="1"' in response.text


def test_changing_only_report_choice_does_not_run(client, monkeypatch):
    admin(client)
    def denied(*args, **kwargs):
        raise AssertionError('Selecting a report ran it')
    monkeypatch.setattr('routes.results_usage_routes.build_usage_report_context', denied)
    assert client.get('/results/usage?report=evidence').status_code == 200
