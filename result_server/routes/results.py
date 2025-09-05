import os
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, abort
)
from utils.results_loader import load_results_table
from utils.otp_manager import send_otp, verify_otp, get_affiliations
from utils.result_file import load_result_file, get_file_confidential_tags

results_bp = Blueprint("results", __name__)
SAVE_DIR = "received"


# ==========================================
# 公開用の結果一覧ページ
# ==========================================
@results_bp.route("/results")
def results():
    rows, columns = load_results_table(public_only=True)
    return render_template("results.html", rows=rows, columns=columns)


# ==========================================
# 機密データ付きの結果ページ（OTP認証付き）
# ==========================================
@results_bp.route("/results_confidential", methods=["GET", "POST"])
def results_confidential():
    # フォーム送信処理
    if request.method == "POST":
        email = request.form.get("email")
        otp = request.form.get("otp")

        if email and not otp:
            # STEP1: メール送信
            success, msg = send_otp(email)
            if success:
                flash("OTPをメールに送信しました")
                session["otp_email"] = email
                session["otp_stage"] = "otp"
            else:
                flash(msg)
                session.pop("otp_email", None)
                session["otp_stage"] = "email"
            return redirect(url_for("results.results_confidential"))

        elif otp:
            # STEP2: OTP検証
            otp_email = session.get("otp_email")
            if otp_email and verify_otp(otp_email, otp):
                session["authenticated_confidential"] = True
                flash("認証成功")
                session.pop("otp_stage", None)  # 認証済みなので削除
            else:
                flash("OTP認証失敗")
                session.pop("otp_email", None)
                session.pop("authenticated_confidential", None)
                session["otp_stage"] = "email"
            return redirect(url_for("results.results_confidential"))

    # OTPステージ判定
    authenticated = session.get("authenticated_confidential", False)
    otp_email = session.get("otp_email")

    if authenticated:
        otp_stage = None  # 認証済みなのでフォームは出さない
    elif otp_email:
        otp_stage = "otp"  # OTP入力待ち
    else:
        otp_stage = "email"  # メール入力待ち


    # 結果テーブル読み込み（confidential制御は utils 内で処理）
    rows, columns = load_results_table(
        public_only=False,
        session_email=otp_email,
        authenticated=authenticated
    )

    return render_template(
        "results_confidential.html",
        rows=rows,
        columns=columns,
        authenticated=authenticated,
        otp_stage=otp_stage
    )

# ==========================================
# 個別結果ファイルの表示/ダウンロード
# ==========================================
@results_bp.route("/results/<filename>")
def show_result(filename):
    tags = get_file_confidential_tags(filename)

    if tags:
        authenticated = session.get("authenticated_confidential", False)
        email = session.get("otp_email")
        affs = get_affiliations(email) if email else []
        if not authenticated or not (set(tags) & set(affs)):
            abort(403, "このファイルにアクセスする権限がありません")

    return load_result_file(filename)
