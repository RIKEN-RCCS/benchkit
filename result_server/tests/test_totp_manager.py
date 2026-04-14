"""Property-based tests for the TOTP manager."""

import base64

import pyotp
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.totp_manager import generate_secret, verify_code


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
