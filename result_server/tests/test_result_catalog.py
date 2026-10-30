"""Catalog lifecycle uses synthetic JSON and disposable SQLite only."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.result_catalog import CatalogUnavailable, ResultCatalog


@pytest.fixture
def catalog(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    store = tmp_path / "catalog"
    store.mkdir(mode=0o700)
    catalog = ResultCatalog(store / "candidates.sqlite3", results)
    catalog.initialize()
    catalog.rebuild()
    return catalog


def put(catalog, name="sample.json", **fields):
    payload = dict(system="SystemA", code="app-a", Exp="CASE0", **fields)
    catalog.replace(name, payload, lambda: (Path(catalog.directory) / name).write_text(json.dumps(payload)))


def test_initialize_is_not_ready_and_read_does_not_create(tmp_path):
    tmp_path.chmod(0o700)
    results = tmp_path / "data"
    results.mkdir()
    c = ResultCatalog(tmp_path / "index", results)
    with pytest.raises(FileNotFoundError):
        c.candidates()
    assert not c.path.exists()
    c.initialize()
    assert c.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(CatalogUnavailable):
        c.candidates()
    c.rebuild()
    assert c.candidates()["total"] == 0


@pytest.mark.parametrize("public,authenticated,tags,expected", [
    (True, False, [], 1), (True, True, ["admin"], 1),
    (False, False, ["admin"], 1), (False, True, [], 1),
    (False, True, ["a"], 2), (False, True, ["a", "b"], 3),
    (False, True, ["admin"], 4), (False, True, ["unrelated"], 1),
])
def test_permission_counts_never_double_count(catalog, public, authenticated, tags, expected):
    for number, visibility in enumerate([None, ["a", "b", "a"], "b", ["secret"]]):
        put(catalog, f"{number}.json", confidential=visibility)
    result = catalog.candidates(public_only=public, authenticated=authenticated, affiliations=tags)
    assert result["total"] == expected
    assert result["rows"][0]["count"] == expected
    assert result["options"]["code"] == [{"value": "app-a", "count": expected}]


def test_private_only_tuple_and_counts_do_not_leak(catalog):
    put(catalog, confidential="secret")
    assert catalog.candidates()["rows"] == []
    assert catalog.candidates()["options"]["system"] == []
    assert catalog.candidates()["total"] == 0


def test_idempotent_replacement_visibility_and_delete(catalog):
    put(catalog)
    put(catalog)
    assert catalog.candidates()["total"] == 1
    catalog.replace("sample.json", {"system": "Other", "code": "unknown-app", "Exp": "E", "confidential": ["a"]},
                    lambda: (Path(catalog.directory) / "sample.json").write_text('{}'))
    assert catalog.candidates()["total"] == 0
    visible = catalog.candidates(public_only=False, authenticated=True, affiliations=["a"])
    assert visible["rows"] == [{"system": "Other", "code": "unknown-app", "exp": "E", "count": 1}]
    catalog.delete("sample.json", lambda: (Path(catalog.directory) / "sample.json").unlink())
    assert catalog.candidates(public_only=False, authenticated=True, affiliations=["admin"])["total"] == 0
    catalog.delete("sample.json", lambda: None)
    assert catalog.candidates()["total"] == 0


def test_stored_file_not_uuid_is_identity(catalog):
    put(catalog, 'first.json', _server_uuid='same')
    put(catalog, 'second.json', _server_uuid='same')
    assert catalog.candidates()['total'] == 2
    catalog.rebuild()
    assert catalog.candidates()['total'] == 2


def test_permission_and_query_filtering_matches_json_loader(catalog):
    from utils.result_records import load_visible_result_json
    for n, tags in enumerate([None, [], "null", "a", ["a", "b"], ["b"], "secret"]):
        put(catalog, f"{n}.json", confidential=tags)
    for public in (True, False):
        for affiliations in ([], ["a"], ["a", "b"], ["admin"]):
            expected = sum(load_visible_result_json(path.name, catalog.directory, affiliations, public, True) is not None
                           for path in Path(catalog.directory).iterdir())
            assert catalog.candidates(public_only=public, authenticated=True, affiliations=affiliations)['total'] == expected


def test_rebuild_reconciles_out_of_band_changes_and_removals(catalog):
    put(catalog)
    file = Path(catalog.directory) / "sample.json"
    file.write_text(json.dumps(dict(system="New", code="other", Exp="E")))
    catalog.rebuild()
    assert catalog.candidates()['rows'][0]['code'] == 'other'
    file.unlink()
    catalog.rebuild()
    assert catalog.candidates()['rows'] == []


@pytest.mark.parametrize('contents', ['{bad', '[]'])
def test_rebuild_failure_is_not_a_public_zero(catalog, contents):
    put(catalog)
    (Path(catalog.directory) / 'bad.json').write_text(contents)
    with pytest.raises(ValueError):
        catalog.rebuild()
    with pytest.raises(CatalogUnavailable):
        catalog.candidates()
    (Path(catalog.directory) / 'bad.json').unlink()
    catalog.rebuild()
    assert catalog.candidates()['total'] == 1


def test_publication_failure_and_process_interruption_leave_dirty(catalog):
    put(catalog)
    with pytest.raises(RuntimeError):
        with catalog.writer():
            raise RuntimeError('synthetic failure after invalidation')
    with pytest.raises(CatalogUnavailable):
        catalog.candidates()
    put(catalog, 'new.json')
    with pytest.raises(CatalogUnavailable):
        catalog.candidates()  # Incremental updates cannot declare a partial baseline complete.
    catalog.rebuild()
    assert catalog.candidates()['total'] == 2


def test_process_crash_after_invalidation_stays_dirty(catalog):
    module_path = str(Path(__file__).resolve().parents[1])
    program = ('import sys,os; sys.path.insert(0,sys.argv[1]); '
               'from utils.result_catalog import ResultCatalog; '
               'c=ResultCatalog(sys.argv[2],sys.argv[3]); guard=c.writer(); '
               'guard.__enter__(); os._exit(17)')
    result = subprocess.run([sys.executable, '-B', '-c', program, module_path,
                             str(catalog.path), catalog.directory], capture_output=True)
    assert result.returncode == 17
    with pytest.raises(CatalogUnavailable):
        catalog.candidates()
    catalog.rebuild()
    assert catalog.candidates()['total'] == 0


def test_lock_serializes_writers_and_rebuild(catalog):
    put(catalog)
    with catalog.writer():
        with pytest.raises(CatalogUnavailable):
            put(catalog, 'new.json')
        with pytest.raises(CatalogUnavailable):
            catalog.rebuild()
        with pytest.raises(CatalogUnavailable):
            catalog.candidates()
    assert not (Path(catalog.directory) / 'new.json').exists()
    assert catalog.candidates()['total'] == 1


def test_contextual_facets_and_paging(catalog):
    for index in range(103):
        catalog.replace(f'{index}.json', dict(system=f'S{index:03}', code='app', Exp='E'), lambda: None)
    data = catalog.candidates(page=2)
    assert data['pages'] == 3 and len(data['rows']) == 50 and data['total'] == 103
    assert data['rows'][0]['system'] == 'S050'
    data = catalog.candidates(system='S001', code='app', exp='E')
    assert data['total'] == 1
    assert data['options']['code'] == [{'value': 'app', 'count': 1}]
    assert len(data['options']['system']) == 103
    assert catalog.candidates(system='missing')['total'] == 0


def test_missing_fields_unknown_names_and_sql_html_text_are_data(catalog):
    catalog.replace('partial.json', {}, lambda: None)
    assert catalog.candidates()['total'] == 1
    assert catalog.candidates()['options']['code'] == []
    payload = {'system': "' OR 1=1--", 'code': '<script>bad</script>', 'Exp': 'unknown'}
    catalog.replace('other.json', payload, lambda: None)
    assert catalog.candidates(system=payload['system'])['total'] == 1


def test_source_mismatch_symlink_and_permissions_rejected(catalog, tmp_path):
    other = tmp_path / 'other'
    other.mkdir()
    with pytest.raises(CatalogUnavailable):
        ResultCatalog(catalog.path, other).candidates()
    (Path(catalog.directory) / 'link.json').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError):
        catalog.rebuild()
    catalog.path.chmod(0o644)
    with pytest.raises(CatalogUnavailable):
        catalog.candidates()


def test_incremental_update_does_not_scan(catalog, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Directory scanned')
    monkeypatch.setattr(Path, 'iterdir', forbidden)
    monkeypatch.setattr(os, 'listdir', forbidden)
    put(catalog)
    assert catalog.candidates()['total'] == 1


def test_rebuild_cli_synthetic_source(tmp_path):
    tmp_path.chmod(0o700)
    results = tmp_path / 'results'
    results.mkdir()
    (results / 'a.json').write_text('{"system":"A","code":"app","Exp":"E"}')
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'result_catalog.py'
    before = (results / 'a.json').read_bytes()
    result = subprocess.run([sys.executable, '-B', str(script), '--catalog', str(tmp_path / 'db'),
                             '--results', str(results), '--initialize'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (results / 'a.json').read_bytes() == before
    assert ResultCatalog(tmp_path / 'db', results).candidates()['total'] == 1
