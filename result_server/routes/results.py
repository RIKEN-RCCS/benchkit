import os
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, abort, current_app
)
from utils.results_loader import load_results_table, load_single_result, load_multiple_results
from utils.user_store import get_user_store
from utils.result_file import load_result_file, get_file_confidential_tags
from utils.system_info import get_all_systems_info

results_bp = Blueprint("results", __name__)


# ==========================================
# 共通関数: ファイルアクセス権限確認
# ==========================================
def check_file_permission(filename, dir_path):
    tags = get_file_confidential_tags(filename, dir_path)
    if not tags:
        return  # 公開ファイル

    authenticated = session.get("authenticated", False)
    email = session.get("user_email")
    store = get_user_store()
    affs = store.get_affiliations(email) if email else []
    if not authenticated or not (set(tags) & set(affs)):
        abort(403, "You do not have permission to access this file")


def serve_confidential_file(filename, dir_path):
    """ファイルアクセス権限確認して送信"""
    check_file_permission(filename, dir_path)
    return load_result_file(filename, dir_path)

# ==========================================
# 公開用の結果一覧ページ
# GET /results/
# ==========================================
@results_bp.route("/", strict_slashes=False)
def results():
    received_dir = current_app.config["RECEIVED_DIR"]
    rows, columns = load_results_table(received_dir, public_only=True)
    systems_info = get_all_systems_info()
    return render_template("results.html", rows=rows, columns=columns, systems_info=systems_info)


# ==========================================
# 機密データ付きの結果ページ（セッション認証）
# ==========================================
def render_confidential_table(template_name, public_only, loader_func=None):
    authenticated = session.get("authenticated", False)
    email = session.get("user_email")

    if loader_func is None:
        loader_func = load_results_table

    received_dir = current_app.config["RECEIVED_DIR"]

    store = get_user_store()
    affs = store.get_affiliations(email) if email else []

    rows, columns = loader_func(
        received_dir,
        public_only=public_only,
        session_email=email,
        authenticated=authenticated,
        affiliations=affs
    )

    systems_info = get_all_systems_info()
    return render_template(
        template_name,
        rows=rows,
        columns=columns,
        authenticated=authenticated,
        systems_info=systems_info
    )


# GET /results/confidential
@results_bp.route("/confidential", methods=["GET"], strict_slashes=False)
def results_confidential():
    return render_confidential_table("results_confidential.html", public_only=False)


# ==========================================
# リグレッション比較ページ
# GET /results/compare
# ==========================================
@results_bp.route("/compare", methods=["GET"])
def result_compare():
    """複数結果のリグレッション比較ページ"""
    files_param = request.args.get("files", "")
    filenames = [f.strip() for f in files_param.split(",") if f.strip()]

    if len(filenames) < 2:
        abort(400, "Select 2 or more results to compare")

    for filename in filenames:
        check_file_permission(filename, current_app.config["RECEIVED_DIR"])

    results = load_multiple_results(filenames, save_dir=current_app.config["RECEIVED_DIR"])

    mixed = False
    if results:
        first_system = results[0]["data"].get("system")
        first_code = results[0]["data"].get("code")
        for r in results[1:]:
            if r["data"].get("system") != first_system or r["data"].get("code") != first_code:
                mixed = True
                break

    return render_template("result_compare.html", results=results, mixed=mixed)


# ==========================================
# 個別結果の詳細ページ
# GET /results/detail/<filename>
# ==========================================
@results_bp.route("/detail/<filename>")
def result_detail(filename):
    """個別結果の詳細ページ（グラフ、データテーブル、ビルド情報）"""
    check_file_permission(filename, current_app.config["RECEIVED_DIR"])
    result = load_single_result(filename, save_dir=current_app.config["RECEIVED_DIR"])
    if result is None:
        abort(404, "Result file not found")
    return render_template("result_detail.html", result=result, filename=filename)


# ==========================================
# 個別結果ファイルの表示/ダウンロード
# GET /results/<filename>
# ==========================================
@results_bp.route("/<filename>")
def show_result(filename):
    return serve_confidential_file(filename, current_app.config["RECEIVED_DIR"])
