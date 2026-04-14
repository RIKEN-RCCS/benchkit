from flask import make_response, render_template


def render_no_store_template(template_name, **context):
    response = make_response(render_template(template_name, **context))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def build_filtered_redirect_args(page, per_page, filter_system, filter_code, filter_exp):
    redirect_args = {"page": page, "per_page": per_page}
    if filter_system is not None:
        redirect_args["system"] = filter_system
    if filter_code is not None:
        redirect_args["code"] = filter_code
    if filter_exp is not None:
        redirect_args["exp"] = filter_exp
    return redirect_args
