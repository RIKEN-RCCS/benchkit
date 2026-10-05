"""Registry state and compact history use scoped data, not execution readiness."""

from datetime import date
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.budget_registry_display import decorate_catalog  # noqa: E402


@pytest.mark.parametrize('enabled,start,end,configured,expected,state', [
    (False, '', '', True, 'Disabled', 'disabled'),
    (False, '2030-01-03', '', False, 'Disabled', 'disabled'),
    (True, '2030-01-03', '', True, 'Not started', 'pending'),
    (True, '', '2030-01-01', True, 'Expired', 'expired'),
    (True, '2030-01-02', '2030-01-02', True, 'Within validity', 'valid'),
    (True, '', '', True, 'Within validity', 'valid'),
    (True, '', '', False, 'Not configured', 'unconfigured'),
])
def test_budget_status(enabled, start, end, configured, expected, state):
    budget = dict(id='budget', label='Example', enabled=enabled, valid_from=start, valid_until=end)
    catalog = dict(budgets=[budget], destinations=[dict(budget_id='budget')] if configured else [], history=[])
    decorate_catalog(catalog, today=date(2030, 1, 2))
    assert budget['status_label'] == expected
    assert budget['status_state'] == state


def test_history_summarizes_changed_field_names_without_values():
    before = dict(id='budget', label='Before', system='Example', enabled=1, valid_from='', valid_until='')
    after = dict(before, label='After', enabled=0)
    row = dict(entity_type='budgets', entity_id='budget', before_json=json.dumps(before), after_json=json.dumps(after))
    catalog = dict(budgets=[after], destinations=[], history=[row])
    decorate_catalog(catalog)
    assert row['display_name'] == 'After'
    assert row['operation'] == 'Updated'
    assert row['changed_fields'] == ['Name', 'Enabled']


@pytest.mark.parametrize('before,after,operation', [
    (None, dict(budget_id='budget', principal='manager@example.org'), 'Added'),
    (dict(budget_id='budget', principal='manager@example.org'), None, 'Removed'),
])
def test_manager_history_names_budget(before, after, operation):
    row = dict(entity_type='budget_managers', entity_id='budget',
               before_json=json.dumps(before), after_json=json.dumps(after))
    budget = dict(id='budget', label='Research', enabled=1, valid_from='', valid_until='')
    catalog = dict(budgets=[budget], destinations=[], history=[row])
    decorate_catalog(catalog)
    assert row['display_name'] == 'Research'
    assert row['operation'] == operation
    assert row['changed_fields'] == ['Manager']
