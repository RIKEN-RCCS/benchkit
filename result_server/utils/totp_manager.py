"""TOTP認証操作モジュール

TOTP秘密鍵の生成、QRコード生成、コード検証を担当する。
状態を持たない純粋なユーティリティモジュール。
"""

import base64
import io

import pyotp
import qrcode

ISSUER_NAME = "BenchKit"


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
        issuer: サービス名（デフォルト: "BenchKit"）

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
