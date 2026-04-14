from utils.results_loader import ALLOWED_PER_PAGE, DEFAULT_PER_PAGE


def parse_table_query_params(args):
    page = args.get("page", 1, type=int)
    per_page = args.get("per_page", DEFAULT_PER_PAGE, type=int)
    filter_system = args.get("system", None)
    filter_code = args.get("code", None)
    filter_exp = args.get("exp", None)

    if per_page not in ALLOWED_PER_PAGE:
        per_page = DEFAULT_PER_PAGE

    return {
        "page": page,
        "per_page": per_page,
        "filter_system": filter_system,
        "filter_code": filter_code,
        "filter_exp": filter_exp,
    }
