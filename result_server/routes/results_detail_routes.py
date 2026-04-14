from flask import abort, current_app, render_template, request

from utils.result_compare_view import load_result_compare_context
from utils.result_detail_view import build_result_detail_context
from utils.result_file import (
    load_permitted_result_json,
    serve_permitted_result_file,
)
from utils.result_records import summarize_result_quality


def serve_confidential_file(filename, dir_path):
    return serve_permitted_result_file(filename, dir_path)


def register_results_detail_routes(results_bp):
    @results_bp.route("/compare", methods=["GET"])
    def result_compare():
        files_param = request.args.get("files", "")
        filenames = [name.strip() for name in files_param.split(",") if name.strip()]

        if len(filenames) < 2:
            abort(400, "Select 2 or more results to compare")

        compare_context = load_result_compare_context(filenames, current_app.config["RECEIVED_DIR"])
        return render_template("result_compare.html", **compare_context)

    @results_bp.route("/detail/<filename>")
    def result_detail(filename):
        result = load_permitted_result_json(
            filename,
            current_app.config["RECEIVED_DIR"],
            not_found_message="Result file not found",
        )
        quality = summarize_result_quality(result)
        detail_context = build_result_detail_context(result, quality, filename)
        return render_template("result_detail.html", result=result, quality=quality, **detail_context)

    @results_bp.route("/<filename>")
    def show_result(filename):
        if filename.endswith(".tgz"):
            return serve_permitted_result_file(
                filename,
                current_app.config["RECEIVED_DIR"],
                current_app.config["RECEIVED_PADATA_DIR"],
            )
        return serve_confidential_file(filename, current_app.config["RECEIVED_DIR"])
