import redis
import random
import string
import time
from typing import List, Tuple
from datetime import datetime, timedelta
from email.mime.text import MIMEText
import smtplib
import json
import os

# -------------------------------
# Redis 接続 (初期化は後で)
# -------------------------------
r = None
prefix = ""  # app から渡す

def init_redis(redis_conn, key_prefix: str = ""):
    global r, prefix
    r = redis_conn
    prefix = key_prefix

# -------------------------------
# メール許可・所属
# -------------------------------
with open("config/allowed_emails.json", encoding="utf-8") as f:
    _ALLOWED = json.load(f)

def is_allowed(email: str) -> bool:
    return email in _ALLOWED

def get_affiliations(email: str) -> List[str]:
    if not is_allowed(email):
        return []
    aff = _ALLOWED[email]
    if isinstance(aff, list):
        return [str(a).strip() for a in aff if str(a).strip()]
    if isinstance(aff, str):
        return [a.strip() for a in aff.split(",") if a.strip()]
    return []

# -------------------------------
# Gmail SMTP 設定
# -------------------------------
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")

# -------------------------------
# OTP 設定
# -------------------------------
OTP_TTL_SECONDS = 5 * 60
MAX_OTP_ATTEMPTS = 5

def generate_otp_code(length=6) -> str:
    return ''.join(random.choices(string.digits, k=length))

def send_otp(email: str) -> Tuple[bool, str]:
    """OTP を生成して Redis に保存してメール送信"""
    public_message = "メールを確認してください。"
    if not is_allowed(email):
        return True, public_message

    code = generate_otp_code()
    now = int(time.time())
    key = f"{prefix}:otp:{email}"

    r.hmset(key, {
        "code": code,
        "expires_at": now + OTP_TTL_SECONDS,
        "attempts_left": MAX_OTP_ATTEMPTS,
    })
    r.expire(key, OTP_TTL_SECONDS)

    # メール送信
    msg = MIMEText(
        f"あなたの認証コード (OTP) は {code} です。\n"
        f"有効期限は {datetime.fromtimestamp(now + OTP_TTL_SECONDS).strftime('%H:%M:%S')} までです。"
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

    return True, public_message

def verify_otp(email: str, code: str) -> bool:
    key = f"{prefix}:otp:{email}"
    data = r.hgetall(key)
    now = int(time.time())
    if not data:
        return False

    if now > int(data.get("expires_at", 0)):
        r.delete(key)
        return False

    attempts_left = int(data.get("attempts_left", MAX_OTP_ATTEMPTS))
    if attempts_left <= 0:
        r.delete(key)
        return False

    if code == data.get("code"):
        r.delete(key)
        return True
    else:
        attempts_left -= 1
        if attempts_left <= 0:
            r.delete(key)
        else:
            r.hset(key, "attempts_left", attempts_left)
        return False

def invalidate_otp(email: str):
    r.delete(f"{prefix}:otp:{email}")

