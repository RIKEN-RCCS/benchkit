from flask import current_app, render_template

from utils.result_file import (
    load_permitted_result_json,
    require_authenticated_session,
    serve_permitted_result_file,
)


def register_estimated_detail_routes(estimated_bp):
    @estimated_bp.route("/<filename>")
    def show_estimated_result(filename):
        require_authenticated_session("Authentication required to view estimated data")
        estimated_dir = current_app.config["ESTIMATED_DIR"]
        return serve_permitted_result_file(filename, estimated_dir)

    @estimated_bp.route("/detail/<filename>")
    def estimated_detail(filename):
        require_authenticated_session("Authentication required to view estimated data")
        estimated_dir = current_app.config["ESTIMATED_DIR"]
        result = load_permitted_result_json(
            filename,
            estimated_dir,
            not_found_message="Estimated result file not found",
        )
        return render_template("estimated_detail.html", result=result, filename=filename)
