from contextlib import contextmanager
import json
from pathlib import Path
import sys
from uuid import UUID

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_cx_persistence import storage
from utils import estimate_list_index
from utils.document_snapshot import DocumentSnapshot, document_snapshot
from utils.encrypted_sqlite import EncryptedDatabaseError
from utils.estimated_list_page import load_estimated_page
from utils.results_loader import load_estimated_results_table, ESTIMATED_FIELD_MAP
from utils.result_catalog import CatalogUnavailable
from utils.table_filters import get_filter_options


def payload(number):
    return {'code':['alpha','beta'][number % 2], 'exp':'case-'+str(number % 3),
            'confidential':[None,'team',['other','team'],'other','null'][number % 5],
            'current_system':{'system':'system-'+str(number % 2),'fom':2.5,'target_nodes':4,
                              'scaling_method':'weakscaling','benchmark':{'system':'base','fom':1,'nodes':2}},
            'future_system':{'system':'future','fom':5,'target_nodes':2},
            'estimate_metadata':{'estimation_result_uuid':str(UUID(int=number+1))},
            'performance_ratio':2.0,'applicability':{'status':'applicable'}}


def seed(storage, count=32):
    with storage.transaction() as conn:
        for number in range(count):
            name='estimate_20261120_120000_'+str(UUID(int=number+1))+'.json'
            storage.put_document('estimates',name,json.dumps(payload(number)).encode(),
                                 conn=conn,update_metadata=False)


@contextmanager
def context(storage):
    app=Flask(__name__);app.extensions['cx_persistence']=storage
    with app.app_context():yield app


def page(storage, affiliations=('admin',), **kwargs):
    return load_estimated_page(storage.roots['estimates'],affiliations=affiliations,
                               page=kwargs.pop('page',1),per_page=kwargs.pop('per_page',50),**kwargs)


@pytest.mark.parametrize('affiliations',[[],['team'],['other'],['admin'],['revoked']])
@pytest.mark.parametrize('filters',[{}, {'filter_code':'alpha'}, {'filter_system':'system-1'},
                                   {'filter_exp':'case-2'}, {'filter_code':''}, {'page':99}])
def test_indexed_page_rows_options_permissions_and_order_match_legacy(storage, affiliations, filters):
    seed(storage)
    with context(storage):
        actual=page(storage,affiliations,**filters)
        expected=load_estimated_results_table(storage.roots['estimates'],public_only=False,
            authenticated=True,affiliations=affiliations,per_page=50,**filters)
        options=get_filter_options(storage.roots['estimates'],public_only=False,
            authenticated=True,affiliations=affiliations,field_map=ESTIMATED_FIELD_MAP)
    assert actual[:3]==expected and actual[3]==options


@pytest.mark.parametrize('affiliations', [[], ['team'], ['admin']])
@pytest.mark.parametrize('filter_code', [None, 'beta', 'missing'])
def test_filesystem_page_matches_existing_loader(tmp_path, monkeypatch, affiliations, filter_code):
    monkeypatch.setattr('utils.profile_storage.configured_store', lambda: None)
    for number in range(7):
        name = 'estimate_20261120_120000_' + str(UUID(int=number + 1)) + '.json'
        (tmp_path / name).write_text(json.dumps(payload(number)))
    with Flask(__name__).app_context():
        actual = load_estimated_page(str(tmp_path), affiliations=affiliations,
                                     page=99, per_page=50, filter_code=filter_code)
        expected = load_estimated_results_table(str(tmp_path), public_only=False,
            authenticated=True, affiliations=affiliations, page=99, per_page=50,
            filter_code=filter_code)
        options = get_filter_options(str(tmp_path), public_only=False,
            authenticated=True, affiliations=affiliations, field_map=ESTIMATED_FIELD_MAP)
    assert actual[:3] == expected
    assert actual[3] == options


def test_only_selected_page_documents_are_loaded(storage, monkeypatch):
    seed(storage,350)
    original=DocumentSnapshot.documents;selected=[]
    def documents(self,role,names=None):
        assert names is not None
        selected.extend(names)
        yield from original(self,role,names)
    monkeypatch.setattr(DocumentSnapshot,'documents',documents)
    with context(storage):
        rows,_,pagination,_=page(storage,page=2,per_page=50)
    assert len(rows)==len(selected)==50 and pagination['total']==350


def test_affiliation_change_is_not_cached(storage):
    seed(storage)
    with context(storage):
        granted=page(storage,['team'])
        revoked=page(storage,[])
    assert granted[2]['total']>revoked[2]['total']
    assert granted[3]!=revoked[3] or granted[2]!=revoked[2]


def test_receive_replace_delete_and_failed_write_keep_index_consistent(storage):
    seed(storage,1)
    name=storage.names('estimates')[0]
    with context(storage):
        before=page(storage)
        def failed():raise RuntimeError('synthetic write failure')
        changed=payload(1)
        with pytest.raises(RuntimeError):storage.put_document('estimates',name,json.dumps(changed).encode(),index_metadata=failed)
        assert page(storage)==before
        storage.put_document('estimates',name,json.dumps(changed).encode(),update_metadata=False)
        assert page(storage)[0][0]['code']=='beta'
        with storage.transaction() as conn:conn.execute("DELETE FROM cx_objects WHERE role='estimates' AND name=?",(name,))
        assert page(storage)[2]['total']==0


@pytest.mark.parametrize('damage',['not_ready','source_hash','missing_entry','wrong_tags'])
def test_broken_index_fails_closed_without_scanning_canonical(storage,damage):
    seed(storage,1)
    if damage=='wrong_tags':
        raw=json.dumps({**payload(0),'confidential':'private'}).encode()
        storage.put_document('estimates',storage.names('estimates')[0],raw,update_metadata=False)
    with storage._connect() as conn:
        if damage=='not_ready':conn.execute('UPDATE estimate_list_state SET ready=0')
        elif damage=='source_hash':conn.execute("UPDATE estimate_list_entries SET source_sha='wrong'")
        elif damage=='missing_entry':conn.execute('DELETE FROM estimate_list_entries')
        else:
            # Deliberately corrupt only the derived permission projection.
            conn.execute("UPDATE estimate_list_entries SET public=1")
        conn.commit()
    with context(storage), pytest.raises(CatalogUnavailable):page(storage,[])


def test_old_database_fallback_and_explicit_rebuild_do_not_change_values(storage):
    seed(storage,15)
    with context(storage):expected=page(storage,['team'])
    with storage._connect() as conn:
        conn.execute('DROP TABLE estimate_list_tags');conn.execute('DROP TABLE estimate_list_entries')
        conn.execute('DROP TABLE estimate_list_state')
        conn.execute("INSERT INTO cx_values VALUES('sessions','expired','retained',0)")
        conn.commit()
    with context(storage):assert page(storage,['team'])==expected
    storage.rebuild_estimate_list()
    with context(storage):assert page(storage,['team'])==expected
    with storage._connect(readonly=True) as conn:
        assert conn.execute("SELECT value FROM cx_values WHERE namespace='sessions' AND key='expired'").fetchone()[0]=='retained'


def test_batched_canonical_reader_checks_hash_and_supports_multiple_chunks(storage):
    seed(storage,1);name=storage.names('estimates')[0]
    item=payload(0);item['unused']='x'*(1024*1024+13)
    storage.put_document('estimates',name,json.dumps(item).encode(),update_metadata=False)
    with context(storage), document_snapshot() as snapshot:
        assert list(snapshot.documents('estimates',[name]))==[(name,item)]
    with storage._connect() as conn:
        conn.execute("UPDATE cx_chunks SET data=? WHERE role='estimates' AND name=? AND ordinal=0",(b'broken',name));conn.commit()
    with context(storage),pytest.raises(EncryptedDatabaseError):page(storage)


def test_failed_rebuild_rolls_back_state(storage):
    seed(storage,1)
    with storage._connect() as conn:
        conn.execute("UPDATE cx_chunks SET data=? WHERE role='estimates'",(b'broken',));conn.commit()
    with pytest.raises(EncryptedDatabaseError):storage.rebuild_estimate_list()
    with storage._connect(readonly=True) as conn:
        assert tuple(conn.execute('SELECT version,ready FROM estimate_list_state').fetchone())==(1,1)


def test_copy_cli_rebuild_and_backup_preserve_indexed_pages(storage, capsys):
    from cx_storage import main
    from utils.cx_persistence import CxPersistence

    seed(storage, 15)
    with context(storage):
        expected = page(storage, ['team'])
    plan = storage.path.parent / 'estimate-index-plan.json'
    plan.write_text(json.dumps({
        'database': str(storage.path),
        'key_file': str(storage.storage.key_file),
    }))
    plan.chmod(0o600)
    assert main(['rebuild-estimate-list-copy', '--plan', str(plan)]) == 0
    with context(storage):
        assert page(storage, ['team']) == expected

    backup_path = storage.path.with_name('estimate-index-backup.db')
    storage.backup(backup_path)
    recovered = CxPersistence.open_existing(backup_path, storage.storage.key_file)
    with context(recovered):
        assert page(recovered, ['team']) == expected
    output = capsys.readouterr().out
    assert json.loads(output)['status'] == 'success'
    assert str(storage.path) not in output


def test_legacy_fallback_does_not_create_index_on_read(storage):
    seed(storage, 3)
    with storage._connect() as conn:
        for table in ('estimate_list_tags', 'estimate_list_entries', 'estimate_list_state'):
            conn.execute('DROP TABLE ' + table)
        conn.commit()
    with context(storage):
        assert page(storage)[2]['total'] == 3
    with storage._connect(readonly=True) as conn:
        assert not estimate_list_index.exists(conn)


@pytest.mark.parametrize('column,value', [('code', '"wrong"'), ('public', 0)])
def test_full_check_verifies_derived_fields_against_canonical(storage, column, value):
    seed(storage, 1)
    with storage._connect() as conn:
        conn.execute('UPDATE estimate_list_entries SET ' + column + '=?', (value,))
        conn.commit()
    with pytest.raises(CatalogUnavailable):
        storage.check()
