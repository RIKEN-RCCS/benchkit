VALID_USAGE_PERIOD_TYPES = ("monthly", "semi_annual", "fiscal_year")


def parse_usage_query_params(args, current_fiscal_year):
    period_type = args.get("period_type", "fiscal_year")
    if period_type not in VALID_USAGE_PERIOD_TYPES:
        period_type = "fiscal_year"

    try:
        fiscal_year = int(args.get("fiscal_year", current_fiscal_year))
    except (TypeError, ValueError):
        fiscal_year = current_fiscal_year

    period_filter = args.get("period_filter", "")

    return {
        "period_type": period_type,
        "fiscal_year": fiscal_year,
        "period_filter": period_filter,
    }


def select_usage_periods(periods, period_filter):
    if period_filter and period_filter in periods:
        return period_filter, [period_filter]
    return "", periods
