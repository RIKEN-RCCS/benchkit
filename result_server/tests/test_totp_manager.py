"""Property-based tests for the TOTP manager."""

import base64
import io
from urllib.parse import parse_qs, unquote, urlsplit

import pyotp
import pytest
from PIL import Image
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.totp_manager import generate_secret, verify_code
from utils import totp_manager


@pytest.mark.parametrize("email,issuer", [
    ("user@example.invalid", None),
    ("user+tag@example.invalid", "Research / Portal"),
    ("\u691c\u8a3c@example.invalid", "\u7814\u7a76\u7528"),
    ("user@example.invalid", "Synthetic issuer " * 12),
])
def test_qr_png_and_provisioning_uri(monkeypatch, email, issuer):
    """Exercise the real QR/Pillow path using synthetic enrollment data."""
    secret = "JBSWY3DPEHPK3PXP"
    actual_make = totp_manager.qrcode.make
    observed = []

    def record_make(data, **kwargs):
        observed.append(data)
        return actual_make(data, **kwargs)

    monkeypatch.setattr(totp_manager.qrcode, "make", record_make)
    kwargs = {} if issuer is None else {"issuer": issuer}
    result = totp_manager.generate_qr_base64(secret, email, **kwargs)
    prefix = "data:image/png;base64,"
    assert result.startswith(prefix)
    png = base64.b64decode(result[len(prefix):], validate=True)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(png)) as image:
        assert image.format == "PNG"
        image.verify()
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        assert image.width == image.height > 0
        assert len(image.getcolors(maxcolors=256)) == 2

    uri, = observed
    parsed = urlsplit(uri)
    expected_issuer = totp_manager.ISSUER_NAME if issuer is None else issuer
    assert (parsed.scheme, parsed.netloc) == ("otpauth", "totp")
    assert unquote(parsed.path) == f"/{expected_issuer}:{email}"
    assert parse_qs(parsed.query) == {"secret": [secret], "issuer": [expected_issuer]}


# Feature: totp-authentication
# Property: a TOTP generated from a freshly issued secret should verify.
# Validates: Requirements 1.1, 1.4, 1.5
@settings(max_examples=100)
@given(st.integers(min_value=0, max_value=99))
def test_property1_totp_verify_roundtrip(_iteration):
    """A generated secret should produce a code accepted by verify_code()."""
    secret = generate_secret()

    # Confirm that the generated secret is valid Base32 text.
    base64.b32decode(secret)

    # Generate a current TOTP code and verify it with the helper.
    code = pyotp.TOTP(secret).now()
    assert verify_code(secret, code) is True
