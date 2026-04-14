"""Stateless helpers for TOTP generation, rendering, and verification."""

import base64
import io

import pyotp
import qrcode

ISSUER_NAME = "CX Portal"

# Brute-force protection thresholds.
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5 minutes


def generate_secret() -> str:
    """Generate a Base32-encoded TOTP secret."""
    return pyotp.random_base32()


def generate_totp_uri(secret: str, email: str, issuer: str = ISSUER_NAME) -> str:
    """Build an otpauth URI for authenticator apps."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def generate_qr_base64(secret: str, email: str, issuer: str = ISSUER_NAME) -> str:
    """Return a QR code PNG as a data URI for portal setup pages."""
    uri = generate_totp_uri(secret, email, issuer)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def verify_code(secret: str, code: str) -> bool:
    """Verify a TOTP code with a one-step time window."""
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def check_code_reuse(redis_conn, prefix: str, email: str, code: str) -> bool:
    """Detect replay attempts for recently consumed TOTP codes."""
    key = f"{prefix}totp_used:{email}:{code}"
    if redis_conn.exists(key):
        return True

    # valid_window=1 allows the previous and next 30-second windows,
    # so keep the replay key for at most 90 seconds.
    redis_conn.setex(key, 90, "1")
    return False


def check_rate_limit(redis_conn, prefix: str, email: str) -> tuple:
    """Return whether the user is locked out and the remaining TTL."""
    key = f"{prefix}login_attempts:{email}"
    attempts = redis_conn.get(key)
    if attempts and int(attempts) >= MAX_LOGIN_ATTEMPTS:
        ttl = redis_conn.ttl(key)
        return True, max(ttl, 0)
    return False, 0


def record_failed_attempt(redis_conn, prefix: str, email: str) -> int:
    """Increment and persist the failed-login counter."""
    key = f"{prefix}login_attempts:{email}"
    pipe = redis_conn.pipeline()
    pipe.incr(key)
    pipe.expire(key, LOCKOUT_SECONDS)
    results = pipe.execute()
    return results[0]


def clear_failed_attempts(redis_conn, prefix: str, email: str) -> None:
    """Clear the failed-login counter after successful authentication."""
    key = f"{prefix}login_attempts:{email}"
    redis_conn.delete(key)
