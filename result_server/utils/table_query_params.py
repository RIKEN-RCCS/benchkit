from utils.table_pagination import DEFAULT_PER_PAGE, normalize_per_page


def parse_table_query_params(args):
    page = args.get("page", 1, type=int)
    per_page = args.get("per_page", DEFAULT_PER_PAGE, type=int)
    filter_system = args.get("system", None)
    filter_code = args.get("code", None)
    filter_exp = args.get("exp", None)

    per_page = normalize_per_page(per_page)

    return {
        "page": page,
        "per_page": per_page,
        "filter_system": filter_system,
        "filter_code": filter_code,
        "filter_exp": filter_exp,
    }
