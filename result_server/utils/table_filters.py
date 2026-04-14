import os

from utils.result_records import load_visible_result_json

DEFAULT_RESULT_FIELD_MAP = {"system": "system", "code": "code", "exp": "Exp"}


def filters_are_active(filter_system, filter_code, filter_exp):
    return any(value is not None for value in (filter_system, filter_code, filter_exp))


def get_nested_field(data, field_path):
    keys = field_path.split(".")
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def matches_table_filters(data, filter_system, filter_code, filter_exp, *, field_map):
    if filter_system is not None and get_nested_field(data, field_map["system"]) != filter_system:
        return False
    if filter_code is not None and get_nested_field(data, field_map["code"]) != filter_code:
        return False
    if filter_exp is not None and get_nested_field(data, field_map["exp"]) != filter_exp:
        return False
    return True


def get_filter_options(
    directory,
    *,
    public_only=True,
    authenticated=False,
    affiliations=None,
    field_map=None,
    filter_code=None,
):
    affiliations = affiliations if affiliations is not None else []
    field_map = field_map or DEFAULT_RESULT_FIELD_MAP
    systems = set()
    codes = set()
    experiments = set()

    try:
        files = os.listdir(directory)
    except OSError:
        return {"systems": [], "codes": [], "exps": []}

    for filename in [name for name in files if name.endswith(".json")]:
        result_data = load_visible_result_json(
            filename,
            directory,
            affiliations,
            public_only,
            authenticated,
        )
        if result_data is None:
            continue

        system = get_nested_field(result_data, field_map["system"])
        if system and system != "N/A":
            systems.add(system)

        code = get_nested_field(result_data, field_map["code"])
        if code and code != "N/A":
            codes.add(code)

        exp = get_nested_field(result_data, field_map["exp"])
        if exp and exp != "N/A":
            if not filter_code or get_nested_field(result_data, field_map["code"]) == filter_code:
                experiments.add(exp)

    return {
        "systems": sorted(systems),
        "codes": sorted(codes),
        "exps": sorted(experiments),
    }
