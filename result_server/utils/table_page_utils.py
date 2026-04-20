from flask import make_response, redirect, render_template, url_for


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


def build_table_page_context(
    *,
    rows,
    columns,
    pagination,
    filter_options,
    current_system,
    current_code,
    current_exp,
    current_per_page,
    systems_info=None,
    **extra_context,
):
    context = {
        "rows": rows,
        "columns": columns,
        "pagination": pagination,
        "filter_options": filter_options,
        "current_system": current_system,
        "current_code": current_code,
        "current_exp": current_exp,
        "current_per_page": current_per_page,
    }
    if systems_info is not None:
        context["systems_info"] = systems_info
    context.update(extra_context)
    return context


def build_table_page_context_from_params(
    *,
    rows,
    columns,
    pagination,
    filter_options,
    params,
    systems_info=None,
    **extra_context,
):
    return build_table_page_context(
        rows=rows,
        columns=columns,
        pagination=pagination,
        filter_options=filter_options,
        current_system=params["filter_system"],
        current_code=params["filter_code"],
        current_exp=params["filter_exp"],
        current_per_page=params["per_page"],
        systems_info=systems_info,
        **extra_context,
    )


def build_auth_required_table_page_context(*, per_page, systems_info=None, **extra_context):
    return build_table_page_context(
        rows=[],
        columns=[],
        pagination={"page": 1, "per_page": per_page, "total": 0, "total_pages": 1},
        filter_options={"systems": [], "codes": [], "exps": []},
        current_system=None,
        current_code=None,
        current_exp=None,
        current_per_page=per_page,
        systems_info=systems_info,
        **extra_context,
    )


def render_auth_required_table_page(template_name, *, per_page, systems_info=None, **extra_context):
    context = build_auth_required_table_page_context(
        per_page=per_page,
        systems_info=systems_info,
        **extra_context,
    )
    return render_no_store_template(template_name, **context)


def build_table_page_redirect(endpoint, page, per_page, filter_system, filter_code, filter_exp):
    redirect_args = build_filtered_redirect_args(page, per_page, filter_system, filter_code, filter_exp)
    return redirect(url_for(endpoint, **redirect_args))


def build_table_page_redirect_from_params(endpoint, page, params):
    return build_table_page_redirect(
        endpoint,
        page,
        params["per_page"],
        params["filter_system"],
        params["filter_code"],
        params["filter_exp"],
    )


def render_table_page_response(
    template_name,
    *,
    page_context,
    no_store=False,
    redirect_endpoint=None,
    params=None,
):
    if redirect_endpoint is not None and params is not None:
        pagination = page_context["pagination"]
        if params["page"] != pagination["page"]:
            return build_table_page_redirect_from_params(
                redirect_endpoint,
                pagination["page"],
                params,
            )

    if no_store:
        return render_no_store_template(template_name, **page_context)
    return render_template(template_name, **page_context)
