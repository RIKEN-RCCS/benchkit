from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, abort, current_app
)
from utils.results_loader import load_results_table, load_single_result, load_multiple_results, get_filter_options, ALLOWED_PER_PAGE, DEFAULT_PER_PAGE
from utils.user_store import get_user_store
from utils.result_file import load_result_file, check_file_permission
from utils.system_info import get_all_systems_info

results_bp = Blueprint("results", __name__)


def extract_query_params():
    """request.args から page, per_page, system, code, exp を一括抽出する。

    per_page が ALLOWED_PER_PAGE に含まれない場合は DEFAULT_PER_PAGE を使用。

    Returns:
        {
            "page": int,
            "per_page": int,
            "filter_system": str | None,
            "filter_code": str | None,
            "filter_exp": str | None,
        }
    """
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 100, type=int)
    filter_system = request.args.get("system", None)
    filter_code = request.args.get("code", None)
    filter_exp = request.args.get("exp", None)

    if per_page not in ALLOWED_PER_PAGE:
        per_page = DEFAULT_PER_PAGE

    return {
        "page": page,
        "per_page": per_page,
        "filter_system": filter_system,
        "filter_code": filter_code,
        "filter_exp": filter_exp,
    }


def serve_confidential_file(filename, dir_path):
    """ファイルアクセス権限確認して送信"""
    check_file_permission(filename, dir_path)
    return load_result_file(filename, dir_path)

def _render_results_list(public_only, template_name, redirect_endpoint):
    """results() と results_confidential() の共通ロジック。

    クエリパラメータ抽出、セッション情報取得、データ読み込み、
    ページ範囲外リダイレクト、テンプレートレンダリングを一括処理する。
    """
    params = extract_query_params()
    page = params["page"]
    per_page = params["per_page"]
    filter_system = params["filter_system"]
    filter_code = params["filter_code"]
    filter_exp = params["filter_exp"]

    received_dir = current_app.config["RECEIVED_DIR"]

    # public_only=False の場合のみセッション認証情報を取得
    load_kwargs = dict(
        public_only=public_only,
        page=page, per_page=per_page,
        filter_system=filter_system, filter_code=filter_code, filter_exp=filter_exp,
    )
    filter_kwargs = dict(public_only=public_only)
    template_extra = {}

    if not public_only:
        authenticated = session.get("authenticated", False)
        email = session.get("user_email")
        store = get_user_store()
        affs = store.get_affiliations(email) if email else []
        load_kwargs.update(session_email=email, authenticated=authenticated, affiliations=affs)
        filter_kwargs.update(authenticated=authenticated, affiliations=affs)
        template_extra["authenticated"] = authenticated

    rows, columns, pagination_info = load_results_table(received_dir, **load_kwargs)

    # ページ範囲外の場合はリダイレクト
    if page != pagination_info["page"]:
        redirect_args = {"page": pagination_info["page"], "per_page": per_page}
        if filter_system is not None:
            redirect_args["system"] = filter_system
        if filter_code is not None:
            redirect_args["code"] = filter_code
        if filter_exp is not None:
            redirect_args["exp"] = filter_exp
        return redirect(url_for(redirect_endpoint, **redirect_args))

    filter_options = get_filter_options(received_dir, filter_code=filter_code, **filter_kwargs)
    systems_info = get_all_systems_info()
    return render_template(
        template_name,
        rows=rows, columns=columns, systems_info=systems_info,
        pagination=pagination_info, filter_options=filter_options,
        current_system=filter_system, current_code=filter_code,
        current_exp=filter_exp, current_per_page=per_page,
        **template_extra,
    )


# ==========================================
# 公開用の結果一覧ページ
# GET /results/
# ==========================================
@results_bp.route("/", strict_slashes=False)
def results():
    return _render_results_list(
        public_only=True,
        template_name="results.html",
        redirect_endpoint="results.results",
    )


# ==========================================
# 機密データ付きの結果ページ（セッション認証）
# ==========================================

# GET /results/confidential
@results_bp.route("/confidential", methods=["GET"], strict_slashes=False)
def results_confidential():
    return _render_results_list(
        public_only=False,
        template_name="results_confidential.html",
        redirect_endpoint="results.results_confidential",
    )


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
