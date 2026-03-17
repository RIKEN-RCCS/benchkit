"""認証Blueprint

ログイン、TOTP登録（セットアップ）、ログアウトのルーティングを担当する。
"""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from utils.totp_manager import generate_qr_base64, generate_secret, verify_code
from utils.user_store import get_user_store

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """ログインページ。

    GET: メールアドレス入力フォーム表示
    POST (emailのみ): TOTPコード入力フォーム表示
    POST (email + totp_code): 認証処理
    """
    if request.method == "GET":
        return render_template("auth_login.html", step="email")

    email = request.form.get("email", "").strip()
    totp_code = request.form.get("totp_code", "").strip()

    # Step 1: メールアドレス送信 → TOTPコード入力フォーム表示
    if email and not totp_code:
        # ユーザー列挙攻撃防止: 登録・未登録に関わらず同じレスポンス
        session["_login_email"] = email
        return render_template("auth_login.html", step="totp", email=email)

    # Step 2: TOTPコード検証
    if totp_code:
        email = email or session.pop("_login_email", "")
        if not email:
            return redirect(url_for("auth.login"))

        store = get_user_store()
        user = store.get_user(email)

        if user and user["totp_secret"] and verify_code(user["totp_secret"], totp_code):
            session.clear()
            session["authenticated"] = True
            session["user_email"] = email
            session["user_affiliations"] = user["affiliations"]
            flash("Authentication successful.")
            return redirect(url_for("results.results"))
        else:
            flash("Authentication failed. Please check your code.")
            return render_template("auth_login.html", step="totp", email=email)

    return redirect(url_for("auth.login"))


@auth_bp.route("/setup/<token>", methods=["GET", "POST"])
def setup(token):
    """TOTP登録ページ。

    GET: 招待トークン検証 → QRコード表示
    POST: 確認用TOTPコード検証 → ユーザー登録
    """
    store = get_user_store()
    invitation = store.get_invitation(token)

    if not invitation:
        flash("This invitation link is invalid or has expired.")
        return render_template("auth_setup.html", error=True)

    email = invitation["email"]
    affiliations = invitation["affiliations"]

    if request.method == "GET":
        secret = generate_secret()
        session["_setup_secret"] = secret
        qr_data = generate_qr_base64(secret, email)
        return render_template(
            "auth_setup.html",
            error=False,
            qr_data=qr_data,
            secret=secret,
            email=email,
            token=token,
        )

    # POST: TOTPコード確認
    totp_code = request.form.get("totp_code", "").strip()
    secret = session.get("_setup_secret", "")

    if not secret:
        flash("Session expired. Please use the invitation link again.")
        return redirect(url_for("auth.setup", token=token))

    if verify_code(secret, totp_code):
        store.create_user(email, secret, affiliations)
        store.delete_invitation(token)
        session.pop("_setup_secret", None)
        flash("TOTP registration complete. You can now log in.")
        return redirect(url_for("auth.login"))
    else:
        qr_data = generate_qr_base64(secret, email)
        flash("Invalid code. Please try again.")
        return render_template(
            "auth_setup.html",
            error=False,
            qr_data=qr_data,
            secret=secret,
            email=email,
            token=token,
        )


@auth_bp.route("/logout")
def logout():
    """ログアウト。セッションクリア後、トップページにリダイレクト。"""
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("results.results"))
