"""Bounded HTTPS POST with dedicated authentication and no redirect/proxy fallback."""

from dataclasses import dataclass, field
from http.client import HTTPException
from pathlib import Path
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from .errors import DeliveryError
from .state import read_delivery_key


MAX_RESPONSE_BYTES = 65536


def validate_endpoint(endpoint):
    try:
        parsed = urlsplit(endpoint)
        if (not isinstance(endpoint, str) or not endpoint.isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in endpoint)
                or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or "\\" in endpoint or "%" in endpoint
                or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc)
                or not parsed.path.endswith("/api/v1/runner-observations")
                or any(part in (".", "..") for part in parsed.path.split("/"))):
            raise ValueError
        parsed.port
        return endpoint
    except (ValueError, TypeError, AttributeError):
        raise DeliveryError("invalid_delivery_endpoint") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = field(repr=False)
    retry_after: str = field(default="", repr=False)


class HTTPSDelivery:
    def __init__(self, endpoint, key_file, *, ca_file=None):
        self.endpoint = validate_endpoint(endpoint)
        self.key_file = key_file
        if ca_file is not None:
            try:
                if (not isinstance(ca_file, (str, Path)) or not str(ca_file)
                        or not Path(ca_file).is_absolute() or ".." in Path(ca_file).parts
                        or any(ord(c) < 32 for c in str(ca_file))):
                    raise ValueError
            except (TypeError, ValueError):
                raise DeliveryError("invalid_delivery_ca_file") from None
        self.ca_file = ca_file

    def _tls_context(self):
        try:
            context = ssl.create_default_context()
            if self.ca_file is not None:
                context.load_verify_locations(cafile=self.ca_file)
            return context
        except (OSError, ValueError):
            raise DeliveryError("delivery_tls_failed") from None

    def send(self, raw, *, timeout):
        key = read_delivery_key(self.key_file)
        request = Request(self.endpoint, data=raw, method="POST", headers={
            "X-Collector-Key": key, "Content-Type": "application/json",
            "Accept": "application/json", "Accept-Encoding": "identity"})
        try:
            opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=self._tls_context()))
            try:
                response = opener.open(request, timeout=timeout)
            except HTTPError as error:
                response = error
            with response:
                status = response.code
                if 300 <= status < 400:
                    raise DeliveryError("delivery_redirect_rejected")
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise DeliveryError("invalid_delivery_response")
                if status == 200 and response.headers.get_content_type() != "application/json":
                    raise DeliveryError("invalid_delivery_response")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise DeliveryError("delivery_response_too_large")
                return Response(status, body, response.headers.get("Retry-After", ""))
        except (ssl.SSLError, ssl.CertificateError):
            raise DeliveryError("delivery_tls_failed") from None
        except URLError as error:
            if isinstance(error.reason, ssl.SSLError):
                raise DeliveryError("delivery_tls_failed") from None
            raise DeliveryError("delivery_connection_failed") from None
        except (OSError, TimeoutError, HTTPException):
            raise DeliveryError("delivery_connection_failed") from None
