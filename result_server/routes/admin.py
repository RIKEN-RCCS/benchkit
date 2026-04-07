"""管理者Blueprint

ユーザーCRUD操作と招待リンク管理を提供する。
admin所属を持つ認証済みユーザーのみアクセス可能。
"""

from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from utils.user_store import get_user_store

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _add_no_store_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _get_users_with_totp_status():
    """全ユーザーを取得し、各ユーザーに has_totp フラグを付与して返す。"""
    store = get_user_store()
    users = store.list_users()
    for u in users:
        u["has_totp"] = store.has_totp_secret(u["email"])
    return store, users


def admin_required(f):
    """admin所属を持つ認証済みユーザーのみアクセスを許可するデコレータ。

    未認証: /auth/login にリダイレクト
    admin所属なし: 403エラー
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return _add_no_store_headers(make_response(redirect(url_for("auth.login"))))
        affiliations = session.get("user_affiliations", [])
        if "admin" not in affiliations:
            abort(403)
        return _add_no_store_headers(make_response(f(*args, **kwargs)))

    return decorated


@admin_bp.route("/users", methods=["GET"])
@admin_required
def users():
    """ユーザー一覧ページ。"""
    _, all_users = _get_users_with_totp_status()
    return render_template("admin_users.html", users=all_users, invitation_url=None)


@admin_bp.route("/users/add", methods=["POST"])
@admin_required
def add_user():
    """ユーザー追加。招待トークン生成、招待URL表示。"""
    store = get_user_store()
    email = request.form.get("email", "").strip()
    affiliations_raw = request.form.get("affiliations", "").strip()
    affiliations = [a.strip() for a in affiliations_raw.split(",") if a.strip()]

    if not email:
        flash("Email is required.")
        return redirect(url_for("admin.users"))

    if store.user_exists(email):
        flash(f"User {email} is already registered. Use 'Reinvite' to reset their TOTP.")
        return redirect(url_for("admin.users"))

    token = store.create_invitation(email, affiliations)
    invitation_url = url_for("auth.setup", token=token, _external=True)

    _, all_users = _get_users_with_totp_status()

    flash(f"Invitation created for {email}.")
    return render_template("admin_users.html", users=all_users, invitation_url=invitation_url)


@admin_bp.route("/users/<path:email>/delete", methods=["POST"])
@admin_required
def delete_user(email):
    """ユーザー削除。自分自身の削除は禁止。"""
    if email == session.get("user_email"):
        flash("You cannot delete your own account.")
        return redirect(url_for("admin.users"))
    store = get_user_store()
    store.delete_user(email)
    flash(f"User {email} has been deleted.")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<path:email>/affiliations", methods=["POST"])
@admin_required
def update_affiliations(email):
    """所属情報の更新。"""
    store = get_user_store()
    affiliations_raw = request.form.get("affiliations", "").strip()
    affiliations = [a.strip() for a in affiliations_raw.split(",") if a.strip()]
    store.update_affiliations(email, affiliations)
    flash(f"Affiliations updated for {email}.")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<path:email>/reinvite", methods=["POST"])
@admin_required
def reinvite_user(email):
    """TOTP再登録用招待リンク生成。既存秘密鍵を無効化。"""
    store = get_user_store()

    if not store.user_exists(email):
        flash(f"User {email} not found.")
        return redirect(url_for("admin.users"))

    # 既存秘密鍵を無効化
    store.clear_totp_secret(email)
    affiliations = store.get_affiliations(email)
    token = store.create_invitation(email, affiliations)
    invitation_url = url_for("auth.setup", token=token, _external=True)

    _, all_users = _get_users_with_totp_status()

    flash(f"Reinvitation created for {email}.")
    return render_template("admin_users.html", users=all_users, invitation_url=invitation_url)
