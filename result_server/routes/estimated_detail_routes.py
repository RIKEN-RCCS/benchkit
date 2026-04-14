from flask import current_app, render_template

from utils.result_file import (
    load_authenticated_result_json,
    serve_authenticated_result_file,
)


def register_estimated_detail_routes(estimated_bp):
    @estimated_bp.route("/<filename>")
    def show_estimated_result(filename):
        return serve_authenticated_result_file(
            filename,
            current_app.config["ESTIMATED_DIR"],
            message="Authentication required to view estimated data",
        )

    @estimated_bp.route("/detail/<filename>")
    def estimated_detail(filename):
        result = load_authenticated_result_json(
            filename,
            current_app.config["ESTIMATED_DIR"],
            message="Authentication required to view estimated data",
            not_found_message="Estimated result file not found",
        )
        return render_template("estimated_detail.html", result=result, filename=filename)
