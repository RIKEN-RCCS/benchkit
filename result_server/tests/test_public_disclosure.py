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
from utils.public_disclosure import DisclosurePolicy, digest

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
