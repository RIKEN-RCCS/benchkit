"""Bound explicit report requests without discovering options from stored results."""

from datetime import date

from utils.app_support_matrix import load_app_system_support_matrix
from utils.node_hours import extract_timestamp_from_filename


def definition_options(code=None, system=None, exp=None):
    systems, apps = load_app_system_support_matrix()
    return {
        'systems': sorted(set(systems) | ({system} if system else set())),
        'codes': sorted({row['app'] for row in apps} | ({code} if code else set())),
        'exps': [exp] if exp else [],
    }


def list_requested(args):
    return args.get('search') == '1' or any(
        args.get(key) for key in ('system', 'code', 'exp', 'page', 'per_page'))


def usage_requested(args):
    return args.get('run') == '1' or any(
        args.get(key) for key in ('period_type', 'fiscal_year', 'period_filter', 'code', 'system'))


def usage_selection(args, fiscal_year, period_type, period_filter):
    if not 1 <= fiscal_year <= 9998:
        raise ValueError('Fiscal year must be between 1 and 9998')
    start, end = date(fiscal_year, 4, 1), date(fiscal_year + 1, 4, 1)
    if period_filter and period_type == 'monthly':
        try:
            year, month = map(int, period_filter.split('-'))
            candidate = date(year, month, 1)
        except (TypeError, ValueError):
            raise ValueError('Invalid monthly period') from None
        if not start <= candidate < end:
            raise ValueError('Monthly period is outside the fiscal year')
        if candidate.isoformat()[:7] != period_filter:
            raise ValueError('Monthly period must use YYYY-MM')
        start = candidate
        end = date(year + (month == 12), month % 12 + 1, 1)
    elif period_filter and period_type == 'semi_annual':
        if period_filter not in ('H1', 'H2'):
            raise ValueError('Invalid semi-annual period')
        if period_filter == 'H1':
            end = date(fiscal_year, 10, 1)
        else:
            start = date(fiscal_year, 10, 1)
    elif period_filter and period_type == 'fiscal_year' and period_filter != f'FY{fiscal_year}':
        raise ValueError('Invalid fiscal-year period')
    return {'code': args.get('code', '').strip(), 'system': args.get('system', '').strip(),
            'since': start, 'until': end}


def selected_filename(filename, selection):
    if not selection:
        return True
    timestamp = extract_timestamp_from_filename(filename)
    return timestamp is not None and selection['since'] <= timestamp.date() < selection['until']


def selected_data(data, selection):
    if not selection:
        return True
    if not isinstance(data, dict):
        return False
    current = data.get('current_system')
    system = current.get('system') if isinstance(current, dict) else data.get('system')
    return (not selection['code'] or data.get('code') == selection['code']) and (
        not selection['system'] or system == selection['system'])
