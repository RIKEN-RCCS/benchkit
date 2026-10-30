"""Presentation-only execution views preserve existing actions and history."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest

from test_execution_profiles import (
    _admin_app, _cleanup, _login_admin, _login_user, _profile, _scheduled_trigger,
)
from test_execution_history import request as record_request
from utils.execution_profiles import ExecutionProfileStore


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes, self.stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs), 'parents': list(self.stack)}
        self.nodes.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                       'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                break

    def find(self, key, value=None):
        return [n for n in self.nodes if key in n['attrs']
                and (value is None or n['attrs'][key] == value)]


def selected(document):
    panels = document.find('data-execution-panel')
    assert len(panels) == 4
    return [n['attrs']['data-execution-panel'] for n in panels if 'hidden' not in n['attrs']]


@pytest.fixture
def portal(tmp_path, monkeypatch):
    app, paths = _admin_app(tmp_path / 'profiles.sqlite3')
    store = ExecutionProfileStore(str(tmp_path / 'profiles.sqlite3'))
    store.upsert_profile(_profile(), actor='admin')
    store.upsert_trigger_definition(_scheduled_trigger(), actor='admin')
    record_request(store)

    def denied(*args, **kwargs):
        raise AssertionError('View changes must not contact GitLab or submit')

    monkeypatch.setattr('routes.admin.submit_pipeline_plan', denied)
    monkeypatch.setattr('urllib.request.urlopen', denied)
    client = app.test_client()
    _login_admin(client)
    try:
        yield app, client, store
    finally:
        _cleanup(paths)


@pytest.mark.parametrize('tab', ['runs', 'profiles', 'triggers', 'diagnostics'])
def test_views_are_linkable_without_javascript(portal, tab):
    _, client, _ = portal
    response = client.get('/admin/execution-profiles', query_string={'tab': tab})
    assert response.status_code == 200
    doc = Document(response.text)
    assert selected(doc) == [tab]
    links = doc.find('data-execution-tab')
    assert [n['attrs']['data-execution-tab'] for n in links] == [
        'runs', 'profiles', 'triggers', 'diagnostics']
    assert [n['attrs']['data-execution-tab'] for n in links
            if n['attrs'].get('aria-current') == 'page'] == [tab]
    for link in links:
        url = urlsplit(link['attrs']['href'])
        assert url.path == '/admin/execution-profiles'
        assert parse_qs(url.query)['tab'] == [link['attrs']['data-execution-tab']]


@pytest.mark.parametrize('query', [{}, {'tab': 'invalid'}, {'tab': '<script>alert(1)</script>'}])
def test_default_is_runs_and_creation_is_collapsed(portal, query):
    _, client, _ = portal
    html = client.get('/admin/execution-profiles', query_string=query).text
    doc = Document(html)
    assert selected(doc) == ['runs']
    for name in ('profile-editor', 'trigger-editor'):
        assert 'open' not in doc.find('id', name)[0]['attrs']
    assert 'CI: Not checked' in html
    assert 'No matching Result' in html
    assert '<script>alert(1)</script>' not in html


@pytest.mark.parametrize('query,tab,editor', [
    ({'edit': 'source-system-demoapp-nightly'}, 'profiles', 'profile-editor'),
    ({'edit_trigger': 'source-system-demoapp-nightly-trigger'}, 'triggers', 'trigger-editor'),
])
def test_legacy_edit_links_open_the_editor_after_the_list(portal, query, tab, editor):
    _, client, _ = portal
    query['tab'] = 'diagnostics'
    html = client.get('/admin/execution-profiles', query_string=query).text
    doc = Document(html)
    assert selected(doc) == [tab]
    assert 'open' in doc.find('id', editor)[0]['attrs']
    heading = 'Registered Profiles' if tab == 'profiles' else 'Registered Triggers'
    assert html.index(heading) < html.index('id="' + editor + '"')
    cancel_links = [n for n in doc.find('href') if n['attrs'].get('class') == 'btn btn-secondary'
                    and parse_qs(urlsplit(n['attrs']['href']).query).get('tab') == [tab]]
    assert cancel_links


def test_tabs_preserve_history_queries_but_leave_edit_mode(portal):
    _, client, _ = portal
    query = {'edit': 'source-system-demoapp-nightly', 'history_profile_id': 'park-qws',
             'history_status': 'submitted', 'history_page': '2', 'history_since': '2026-01-01'}
    doc = Document(client.get('/admin/execution-profiles', query_string=query).text)
    for link in doc.find('data-execution-tab'):
        args = parse_qs(urlsplit(link['attrs']['href']).query)
        assert 'edit' not in args and 'edit_trigger' not in args
        for key in ('history_profile_id', 'history_status', 'history_page', 'history_since'):
            assert args[key] == [query[key]]


def test_query_cannot_override_tab_link_url_generation(portal):
    _, client, _ = portal
    doc = Document(client.get('/admin/execution-profiles', query_string={
        '_external': '1', '_scheme': 'javascript', '_anchor': 'injected',
        'history_profile_id': 'park-qws',
    }).text)
    for link in doc.find('data-execution-tab'):
        url = urlsplit(link['attrs']['href'])
        assert not url.scheme and not url.netloc and not url.fragment
        assert parse_qs(url.query)['history_profile_id'] == ['park-qws']


@pytest.mark.parametrize('tab', ['runs', 'profiles', 'triggers', 'diagnostics'])
def test_all_views_retain_admin_authorization(portal, tab):
    _, client, _ = portal
    _login_user(client)
    assert client.get('/admin/execution-profiles', query_string={'tab': tab}).status_code == 403
    with client.session_transaction() as session:
        session.clear()
    assert client.get('/admin/execution-profiles', query_string={'tab': tab}).status_code == 302


@pytest.mark.parametrize('action', ['pause', 'resume', 'delete'])
def test_trigger_actions_return_to_trigger_view(portal, action):
    _, client, _ = portal
    response = client.post('/admin/execution-profiles/triggers/'
                           'source-system-demoapp-nightly-trigger/' + action)
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.location).query)['tab'] == ['triggers']
    assert selected(Document(client.get(response.location).text)) == ['triggers']


def test_profile_delete_returns_to_profiles(portal):
    _, client, _ = portal
    response = client.post('/admin/execution-profiles/source-system-demoapp-nightly/delete')
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.location).query)['tab'] == ['profiles']


@pytest.mark.parametrize('query', ['tab=diagnostics', 'edit=source-system-demoapp-nightly'])
def test_submit_errors_remain_visible_in_runs(portal, query):
    _, client, _ = portal
    response = client.post('/admin/execution-profiles/submit?' + query,
                           data={'profile_id': 'source-system-demoapp-nightly', 'target_ref': 'develop'})
    assert response.status_code == 200
    assert selected(Document(response.text)) == ['runs']
    assert 'confirm_submit is required' in response.text


def test_existing_actions_and_csrf_fields_are_retained(portal):
    app, client, _ = portal
    app.jinja_env.globals['csrf_token'] = lambda: 'synthetic-csrf'
    doc = Document(client.get('/admin/execution-profiles').text)
    actions = {n['attrs']['action'] for n in doc.find('action')}
    assert '/admin/execution-profiles/upsert' in actions
    assert '/admin/execution-profiles/triggers/upsert' in actions
    assert '/admin/execution-profiles/submit' in actions
    assert doc.find('name', 'confirm_submit')
    csrf_fields = doc.find('name', 'csrf_token')
    assert csrf_fields
    assert all(n['attrs']['value'] == 'synthetic-csrf' for n in csrf_fields)
