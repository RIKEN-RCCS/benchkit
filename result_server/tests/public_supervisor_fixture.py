"""Synthetic systemd writer/HTTP reader used only by isolated acceptance tests."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from socketserver import ThreadingMixIn
from wsgiref.simple_server import make_server, WSGIServer

sys.path.insert(0, str(Path(__file__).parents[1]))
from utils.public_delivery import PublicApplication, Publisher
from utils.public_disclosure import DisclosurePolicy, digest
from utils.public_supervisor import SystemdPublicationControl


def writer(root, unit, mode, port, lifetime):
    from utils.cx_persistence import CxPersistence
    from utils.encrypted_sqlite import generate_key
    (root/'secret').mkdir(exist_ok=True, mode=0o700)
    (root/'secret/keys').mkdir(exist_ok=True, mode=0o700)
    (root/'secret/data').mkdir(exist_ok=True, mode=0o700)
    key = root/'secret/keys/key'
    if not key.exists():
        generate_key(key)
    store = CxPersistence(root/'secret/data/store.sqlite3', key,
                          roots={name:str(root/'secret'/name) for name in
                                 ['results', 'estimates', 'artifacts', 'inputs']})
    if not store.path.exists():
        store.initialize()
    name = 'result_20260101_010101_12345678-1234-1234-1234-123456789abc.json'
    value = {'system':'sample', 'code':'demo', 'Exp':'allowed', 'FOM':2.0,
             '_server_uuid':'12345678-1234-1234-1234-123456789abc'}
    store.put_document('results', name, json.dumps(value).encode())
    policy = DisclosurePolicy({name: {'source_sha256':digest(value), 'value':value}})
    command = [sys.executable, str(Path(__file__).resolve()), str(root), 'reader',
               '--port', str(port)]
    control = SystemdPublicationControl(root/'public', root/'state/publisher.json',
                                        65534, unit, command,
                                        reader_environment={'PYTHONPATH':str(Path(__file__).parents[1]),
                                                            'FLASK_SECRET_KEY':'synthetic-test-only-'+'x'*48,
                                                            'RESULT_SERVER_PUBLIC_STATE_DIR':str(root/'sessions'),
                                                            'PYTHONDONTWRITEBYTECODE':'1'})
    if mode == 'crash-active':
        activate = control.activate
        def interrupted_activate(**kwargs):
            activate(**kwargs)
            (root/'failure-time').write_text(str(time.monotonic()))
            os._exit(24)
        control.activate = interrupted_activate
    publisher = Publisher(store, root/'public', root/'state/publisher.json', 65534,
                          control=control, policy=policy)
    publisher.maximum_age = lifetime
    def fault(stage):
        if stage == 'after_export' and mode == 'crash-build':
            (root/'failure-time').write_text(str(time.monotonic()))
            os._exit(23)
        if stage == 'after_export' and mode == 'hung-build':
            while True:
                time.sleep(1)
    publisher.update(fault=fault)
    (root/'writer-complete').write_text('complete')
    if mode == 'withdraw':
        while not (root/'withdraw-now').exists():
            time.sleep(.02)
        started = time.monotonic()
        publisher.expire()
        (root/'withdraw-time').write_text(str(time.monotonic()-started))


def reader(root, port):
    import app
    def no_redis(application, *args):
        application.config.update(REDIS_CONN=None,REDIS_PREFIX='synthetic:',AUTH_REQUIRES_REDIS=False)
    app._configure_redis = no_redis
    application = PublicApplication(root/'public', 0)
    probe = root/'access-probe.json'
    if probe.exists() and any((root/'public/generations').glob('*/received_padata/*')):
        from utils.public_delivery import read_current
        generation, _ = read_current(root/'public')
        assert next((generation/'received').iterdir()).read_bytes()
        assert next((generation/'received_padata').iterdir()).read_bytes()
        denied = []
        for path in json.loads(probe.read_text()):
            try:
                with open(path, 'rb') as stream:
                    stream.read(1)
            except PermissionError:
                denied.append(True)
            else:
                raise AssertionError('Private file accessible to public service')
        (root/'sessions/access.json').write_text(json.dumps(denied))
    def entry(environ, start_response):
        if environ['PATH_INFO'] == '/stream':
            from utils.public_delivery import read_current
            generation, _ = read_current(root/'public')
            name = next((generation/'received').iterdir())
            stream = name.open('rb')
            # Retain an open file and a descendant that leaves its process group.
            import subprocess
            child = subprocess.Popen([sys.executable, '-c', 'import os,time; os.setsid(); time.sleep(90)'])
            (root/'sessions/child-pid').write_text(str(child.pid))
            start_response('200 OK', [('Content-Type','application/octet-stream')])
            def body():
                try:
                    while True:
                        yield stream.read() or b'synthetic-stream\n'
                        stream.seek(0)
                        time.sleep(.02)
                finally:
                    stream.close()
            return body()
        return application(environ, start_response)
    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads = True
    with make_server('127.0.0.1', port, entry, server_class=Server) as server:
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('mode')
    parser.add_argument('--unit')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--lifetime', type=float, default=30)
    args = parser.parse_args()
    if args.mode == 'reader':
        reader(args.root, args.port)
    else:
        writer(args.root, args.unit, args.mode, args.port, args.lifetime)


if __name__ == '__main__':
    main()
