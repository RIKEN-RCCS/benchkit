import os
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, abort, send_from_directory
)
from utils.results_loader import load_results_table, load_estimated_results_table
#from utils.otp_manager import get_affiliations
from utils.otp_redis_manager import send_otp, verify_otp, invalidate_otp, is_allowed, get_affiliations
from utils.result_file import load_result_file, get_file_confidential_tags

results_bp = Blueprint("results", __name__)
SAVE_DIR = "received"
ESTIMATE_DIR = "estimated_results"


# ==========================================
# 共通関数: ファイルアクセス権限確認
# ==========================================
def check_file_permission(filename, session_key_authenticated, session_key_email, dir_path):
    tags = get_file_confidential_tags(filename, dir_path)
    if not tags:
        return  # 公開ファイル

    authenticated = session.get(session_key_authenticated, False)
    email = session.get(session_key_email)
    affs = get_affiliations(email) if email else []
    if not authenticated or not (set(tags) & set(affs)):
        abort(403, "このファイルにアクセスする権限がありません")


def serve_confidential_file(filename, dir_path, session_key_authenticated, session_key_email):
    """ファイルアクセス権限確認して送信"""
    check_file_permission(filename, session_key_authenticated, session_key_email, dir_path)
    #return send_from_directory(dir_path, filename, as_attachment=True)
    return load_result_file(filename, dir_path)

# ==========================================
# 公開用の結果一覧ページ
# ==========================================
@results_bp.route("results", strict_slashes=False)
def results():
    rows, columns = load_results_table(public_only=True)
    return render_template("results.html", rows=rows, columns=columns)


# ==========================================
# 機密データ付きの結果ページ（OTP認証付き）
# ==========================================
def handle_otp_post(session_key_authenticated, session_key_email, route_name):
    email = request.form.get("email")
    otp = request.form.get("otp")

    if email and not otp:
        success, msg = send_otp(email)
        flash(msg)
        if success and is_allowed(email):
            session.clear()
            session[session_key_email] = email
            session["otp_stage"] = "otp"
        else:
            session.clear()
            session["otp_stage"] = "email"
        return redirect(url_for(route_name))

    elif otp:
        otp_email = session.get(session_key_email)
        if otp_email and verify_otp(otp_email, otp):
            session.clear()
            session[session_key_authenticated] = True
            flash("認証成功")
        else:
            session.clear()
            flash("認証失敗")
        return redirect(url_for(route_name))



def render_confidential_table(template_name, public_only, session_key_authenticated, session_key_email, loader_func=None):
    authenticated = session.get(session_key_authenticated, False)
    otp_email = session.get(session_key_email)

    if authenticated:
        otp_stage = None
    elif otp_email:
        otp_stage = "otp"
    else:
        otp_stage = "email"

    # ローダー関数を使い分ける
    if loader_func is None:
        # デフォルトは通常の results
        loader_func = load_results_table

    rows, columns = loader_func(
        public_only=public_only,
        session_email=otp_email,
        authenticated=authenticated
    )

    return render_template(
        template_name,
        rows=rows,
        columns=columns,
        authenticated=authenticated,
        otp_stage=otp_stage
    )


@results_bp.route("results_confidential", methods=["GET", "POST"], strict_slashes=False)
def results_confidential():
    if request.method == "POST":
        return handle_otp_post("authenticated_confidential", "otp_email", "results.results_confidential")
    return render_confidential_table("results_confidential.html", public_only=False,
                                     session_key_authenticated="authenticated_confidential",
                                     session_key_email="otp_email")


@results_bp.route("estimated_results", methods=["GET", "POST"], strict_slashes=False)
def estimated_results():
    if request.method == "POST":
        return handle_otp_post("authenticated_estimated", "otp_email_estimated", "results.estimated_results")
    return render_confidential_table("estimated_results.html", public_only=False,
                                     session_key_authenticated="authenticated_estimated",
                                     session_key_email="otp_email_estimated", loader_func=load_estimated_results_table)


# ==========================================
# 個別結果ファイルの表示/ダウンロード
# ==========================================
@results_bp.route("results/<filename>")
def show_result(filename):
    return serve_confidential_file(filename, SAVE_DIR, "authenticated_confidential", "otp_email")


@results_bp.route("estimated_results/<filename>")
def show_estimated_result(filename):
    return serve_confidential_file(filename, ESTIMATE_DIR, "authenticated_estimated", "otp_email_estimated")
