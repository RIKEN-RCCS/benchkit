import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
from utils.cx_persistence import CxPersistence
from utils.encrypted_sqlite import generate_key
from utils.public_disclosure import AutomaticDisclosure, DisclosurePolicy, digest

SECRET = 'synthetic-do-not-publish'
UUID = '12345678-1234-1234-1234-123456789abc'
NAME = 'result_20260101_010101_' + UUID + '.json'
ARCHIVE = 'padata_20260101_010101_' + UUID + '.tgz'


@pytest.fixture
def store(tmp_path):
    for name in ['data', 'keys', 'results', 'estimates', 'artifacts', 'inputs']:
        (tmp_path/name).mkdir(mode=0o700)
    key = tmp_path/'keys/key'
    generate_key(key)
    value = CxPersistence(tmp_path/'data/cx.db', key, roots={k:str(tmp_path/k) for k in ['results','estimates','artifacts','inputs']})
    value.initialize()
    return value


def tar(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, data in members.items():
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


def fixture(store):
    source = {'system':'sample','code':'demo','Exp':'allowed','FOM':2.0,'_server_uuid':UUID,
              'description':SECRET,'profile_data':{'ncu_options':SECRET},
              'source_info':{'branch':SECRET},'fom_breakdown':{'sections':[{'name':SECRET,'artifacts':[{'type':'file_reference','path':SECRET}]}]}}
    payload = tar({'public.txt':b'approved result', 'private.txt':SECRET.encode()})
    store.put_document('results', NAME, json.dumps(source).encode())
    store.put('artifacts', ARCHIVE, io.BytesIO(payload), limit=len(payload))
    allowed = {'system':'sample','code':'demo','Exp':'allowed','FOM':2.0,'_server_uuid':UUID}
    policy = DisclosurePolicy({NAME:{'source_sha256':digest(source),'value':allowed}},
                              {ARCHIVE:{'source_sha256':hashlib.sha256(payload).hexdigest(),
                                        'members':{'public.txt':hashlib.sha256(b'approved result').hexdigest()}}})
    return source, policy


def test_unreviewed_archive_content_is_denied():
    raw = tar({'public.txt':b'changed'})
    policy = DisclosurePolicy(archives={ARCHIVE:{'source_sha256':hashlib.sha256(raw).hexdigest(),
                            'members':{'public.txt':hashlib.sha256(b'expected').hexdigest()}}})
    assert policy.archive(ARCHIVE,raw,maximum_bytes=1024) is None


@pytest.mark.parametrize('column', [0, 1])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), 10**400])
def test_metric_selection_preserves_inputs_and_finite_values(column, value):
    import copy
    import pickle
    from utils.public_projection import public_document
    layout = {'x_axis': {'name': 'x'}, 'y_axis': {'name': 'y'}, 'columns': ['x', 'y']}
    row = [1, 2]
    row[column] = value
    source = {'code': 'demo', 'metrics': {
        'scalar': {'bad': value, 'finite': 7, 'hidden': 99},
        'vector': {'x_axis': layout['x_axis'], 'y_axis': layout['y_axis'],
                   'table': {'columns': layout['columns'], 'rows': [row]}}}}
    projected = public_document(copy.deepcopy(source))
    before = pickle.dumps((source, projected))
    policy = AutomaticDisclosure({'demo': {'scalar_metrics': ['bad', 'finite'],
                                         'vector_layout': layout}})
    result = policy.document(NAME, source, projected)
    assert pickle.dumps((source, projected)) == before
    assert result['metrics']['scalar']['finite'] == 7
    assert 'hidden' not in result['metrics']['scalar']
    if type(value) is int:
        assert result['metrics']['scalar']['bad'] == value
        assert result['metrics']['vector'] == source['metrics']['vector']
    else:
        assert 'bad' not in result['metrics']['scalar']
        assert 'vector' not in result['metrics']


@pytest.mark.parametrize('member', ['/data.csv', 'metrics/../data.csv'])
def test_unsafe_output_member_rejected_before_reading_archive(member, monkeypatch):
    def unexpected_open(*args, **kwargs):
        pytest.fail('An ineligible output name must be rejected regardless of the input contents')

    monkeypatch.setattr(tarfile, 'open', unexpected_open)
    rule = {'member': member, 'columns': ['seconds']}
    assert AutomaticDisclosure({}).numeric_archive(b'', rule, 1024) is None
