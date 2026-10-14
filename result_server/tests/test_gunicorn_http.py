"""Check the HTTP parsing behavior required by the WSGI deployment."""

import pytest

from gunicorn.config import Config
from gunicorn.http.errors import ChunkMissingTerminator, InvalidHeader, InvalidRequestLine
from gunicorn.http.parser import RequestParser


def parse_request(raw, parser):
    config = Config()
    config.set('http_parser', parser)
    return next(RequestParser(config, iter([raw]), ('127.0.0.1', 12345)))


@pytest.mark.parametrize('parser', ['auto', 'python'])
def test_wsgi_http_request_body(parser):
    request = parse_request(
        b'POST /api/ingest/result HTTP/1.1\r\nHost: example.test\r\n'
        b'Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}', parser)
    assert request.path == '/api/ingest/result'
    assert request.body.read() == b'{}'


@pytest.mark.parametrize('parser', ['auto', 'python'])
@pytest.mark.parametrize('raw,error', [
    (b'GET relative HTTP/1.1\r\nHost: example.test\r\n\r\n', InvalidRequestLine),
    (b'GET / HTTP/1.1\r\nHost: example.test\r\nX-Test: a\x01b\r\n\r\n', InvalidHeader),
    (b'GET / HTTP/1.1\r\nHost: example.test\r\nHost: other.test\r\n\r\n', InvalidHeader),
    (b'POST / HTTP/1.1\r\nHost: example.test\r\n'
     b'Content-Type: application/json\r\nContent-Type: text/plain\r\n'
     b'Content-Length: 0\r\n\r\n', InvalidHeader),
])
def test_wsgi_rejects_ambiguous_http_input(parser, raw, error):
    with pytest.raises(error):
        parse_request(raw, parser)


CHUNKED_REQUEST = (
    b'POST /api/ingest/result HTTP/1.1\r\nHost: example.test\r\n'
    b'Transfer-Encoding: chunked\r\n\r\n'
)


@pytest.mark.parametrize('parser', ['auto', 'python'])
def test_wsgi_chunked_request_body(parser):
    request = parse_request(CHUNKED_REQUEST + b'2\r\n{}\r\n0\r\n\r\n', parser)
    assert request.body.read() == b'{}'


@pytest.mark.parametrize('parser', ['auto', 'python'])
def test_wsgi_rejects_truncated_chunked_body(parser):
    request = parse_request(CHUNKED_REQUEST + b'2\r\n{}\r\n0\r\n', parser)
    with pytest.raises(ChunkMissingTerminator):
        request.body.read()
