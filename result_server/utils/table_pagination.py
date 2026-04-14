from math import ceil


ALLOWED_PER_PAGE = (50, 100, 200)
DEFAULT_PER_PAGE = 100


def normalize_per_page(per_page):
    if per_page not in ALLOWED_PER_PAGE:
        return DEFAULT_PER_PAGE
    return per_page


def paginate_list(items, page, per_page):
    total = len(items)
    total_pages = max(1, ceil(total / per_page)) if total > 0 else 1

    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = items[start:end]

    pagination_info = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }
    return paginated_items, pagination_info
