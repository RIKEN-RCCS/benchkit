import os
import secrets
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
import json
from typing import List, Tuple

# OTP の有効期限（分）
OTP_EXP_MINUTES = 5
otp_storage = {}

# allowed_emails.json は email -> [affiliations] の辞書を想定
with open("config/allowed_emails.json", encoding="utf-8") as f:
    _ALLOWED = json.load(f)

# Gmail の SMTP 設定（環境変数から取得）
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")


def is_allowed(email: str) -> bool:
    """許可されたメールアドレスか判定"""
    return email in _ALLOWED


def get_affiliations(email: str) -> List[str]:
    """メールアドレスに紐づく所属を返す"""
    if not is_allowed(email):
        return []
    aff = _ALLOWED[email]
    if isinstance(aff, list):
        return [str(a).strip() for a in aff if str(a).strip()]
    if isinstance(aff, str):
        return [a.strip() for a in aff.split(",") if a.strip()]
    return []


def send_otp(email: str) -> Tuple[bool, str]:
    """OTP を生成してメール送信"""
    if not is_allowed(email):
        return False, "許可されていないメールアドレスです"

    otp = str(secrets.randbelow(1000000)).zfill(6)
    expire = datetime.now() + timedelta(minutes=OTP_EXP_MINUTES)
    otp_storage[email] = {"value": otp, "expire": expire}

    msg = MIMEText(
        f"あなたの認証コード (OTP) は {otp} です。\n"
        f"有効期限は {expire.strftime('%H:%M:%S')} までです。"
    )
    msg["Subject"] = "OTP 認証コード"
    msg["From"] = SMTP_USER
    msg["To"] = email

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [email], msg.as_string())
    except Exception as e:
        return False, f"メール送信失敗: {e}"

    return True, ""


def verify_otp(email: str, otp: str) -> bool:
    """OTP を検証"""
    stored = otp_storage.get(email)
    if stored and stored["value"] == otp and datetime.now() < stored["expire"]:
        return True
    return False
