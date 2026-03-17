"""totp_managerモジュールのプロパティベーステスト"""

import base64

import pyotp
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.totp_manager import generate_secret, verify_code


# Feature: totp-authentication, Property 1: TOTP検証ラウンドトリップ
# 任意の生成された秘密鍵に対して、pyotp.TOTP(secret).now()で生成したコードが
# verify_code()で検証成功することを確認する。
# Validates: Requirements 1.1, 1.4, 1.5
@settings(max_examples=100)
@given(st.integers(min_value=0, max_value=99))
def test_property1_totp_verify_roundtrip(_iteration):
    """生成された秘密鍵で作成したTOTPコードは、verify_codeで検証成功する。"""
    secret = generate_secret()

    # 秘密鍵が有効なBase32文字列であることを確認
    base64.b32decode(secret)

    # 現在時刻のTOTPコードを生成し、verify_codeで検証
    code = pyotp.TOTP(secret).now()
    assert verify_code(secret, code) is True
