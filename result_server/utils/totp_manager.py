"""TOTP認証操作モジュール

TOTP秘密鍵の生成、QRコード生成、コード検証を担当する。
状態を持たない純粋なユーティリティモジュール。
"""

import base64
import io
import time

import pyotp
import qrcode

ISSUER_NAME = "CX Portal"

# ブルートフォース対策: 最大試行回数とロックアウト時間
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5分


def generate_secret() -> str:
    """Base32エンコードされたTOTP秘密鍵を生成する。

    Returns:
        Base32エンコードされた秘密鍵文字列
    """
    return pyotp.random_base32()


def generate_totp_uri(
    secret: str, email: str, issuer: str = ISSUER_NAME
) -> str:
    """otpauth URIを生成する。

    Args:
        secret: Base32エンコードされた秘密鍵
        email: ユーザーのメールアドレス
        issuer: サービス名（デフォルト: "CX Portal"）

    Returns:
        otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}
    """
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def generate_qr_base64(
    secret: str, email: str, issuer: str = ISSUER_NAME
) -> str:
    """QRコード画像をBase64エンコードされたPNG文字列として返す。

    Args:
        secret: Base32エンコードされた秘密鍵
        email: ユーザーのメールアドレス
        issuer: サービス名

    Returns:
        "data:image/png;base64,..." 形式の文字列
    """
    uri = generate_totp_uri(secret, email, issuer)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def verify_code(secret: str, code: str) -> bool:
    """TOTPコードを検証する。前後1ステップ（30秒）の時間ずれを許容。

    Args:
        secret: Base32エンコードされた秘密鍵
        code: ユーザーが入力した6桁のコード

    Returns:
        検証成功ならTrue
    """
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def check_code_reuse(redis_conn, prefix: str, email: str, code: str) -> bool:
    """TOTPコードのリプレイ攻撃を検出する。

    同じコードが有効期間内（90秒: 30秒×3ウィンドウ）に再利用されていないか確認。

    Returns:
        True = リプレイ（使用済み）, False = 未使用
    """
    key = f"{prefix}totp_used:{email}:{code}"
    if redis_conn.exists(key):
        return True
    # 90秒間記録（valid_window=1なので前後30秒 = 最大90秒）
    redis_conn.setex(key, 90, "1")
    return False


def check_rate_limit(redis_conn, prefix: str, email: str) -> tuple:
    """ログイン試行回数を確認する。

    Returns:
        (is_locked: bool, remaining_seconds: int)
    """
    key = f"{prefix}login_attempts:{email}"
    attempts = redis_conn.get(key)
    if attempts and int(attempts) >= MAX_LOGIN_ATTEMPTS:
        ttl = redis_conn.ttl(key)
        return True, max(ttl, 0)
    return False, 0


def record_failed_attempt(redis_conn, prefix: str, email: str) -> int:
    """失敗した試行を記録する。

    Returns:
        現在の試行回数
    """
    key = f"{prefix}login_attempts:{email}"
    pipe = redis_conn.pipeline()
    pipe.incr(key)
    pipe.expire(key, LOCKOUT_SECONDS)
    results = pipe.execute()
    return results[0]


def clear_failed_attempts(redis_conn, prefix: str, email: str) -> None:
    """ログイン成功時に試行回数をリセットする。"""
    key = f"{prefix}login_attempts:{email}"
    redis_conn.delete(key)
