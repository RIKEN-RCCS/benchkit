"""Browser-free data and fallback checks; layout and JavaScript are manual."""

from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import sys

import pytest
from flask import render_template

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs()
from utils.estimated_detail_view import build_estimated_detail_context
from utils.result_compare_view import build_result_compare_context
from utils.result_detail_view import build_result_detail_context


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)

    def by_id(self, identifier):
        return next(attrs for _, attrs in self.tags if attrs.get("id") == identifier)


@pytest.fixture
def app():
    return build_portal_shell_app(templates_dir=str(Path(__file__).resolve().parents[1] / "templates"))


def result(rows):
    return {"code": "example", "system": "Example", "Exp": "sample", "FOM": 2, "FOM_unit": "s",
            "metrics": {"vector": {"x_axis": {"name": "Size", "unit": "bytes"},
                                   "table": {"columns": ["Size", "<img src=x onerror=alert(1)>"],
                                             "rows": rows}}}}


@pytest.mark.parametrize("rows", [[], [[10, 0]], [[1, -2], [10, 0], [100, 8]]])
def test_detail_preserves_vector_data_and_independent_table(app, rows):
    data = result(rows)
    with app.test_request_context():
        html = render_template("result_detail.html", result=data, quality={},
                               **build_result_detail_context(data, {}))
    markup = Markup(html)
    assert json.loads(markup.by_id("vectorData")["data-vector"]) == data["metrics"]["vector"]
    assert "Vector Metrics - Data Table" in "".join(markup.text)
    assert any(tag == "table" for tag, _ in markup.tags)
    assert any(tag == "noscript" for tag, _ in markup.tags)
    assert "Chart unavailable" in "".join(markup.text)
    assert "hidden" in markup.by_id("chartFallback")
    assert not any(tag == "img" and attrs.get("onerror") == "alert(1)" for tag, attrs in markup.tags)


def test_comparison_preserves_missing_and_zero_values_without_interpreting_them(app):
    data = result([[1, 2]])
    data["metrics"]["vector"]["table"]["rows"] = [[1, -2], [10, None], [100, 0], [1000, ""]]
    results = [{"timestamp": f"2030-01-0{i + 1} 12:00:00", "data": deepcopy(data)} for i in range(3)]
    results[0]["data"]["FOM"] = 0
    results[1]["data"].pop("FOM")
    with app.test_request_context():
        html = render_template("result_compare.html", **build_result_compare_context(results))
    markup = Markup(html)
    assert json.loads(markup.by_id("resultsJsonData")["data-results"]) == results
    assert json.loads(markup.by_id("compareConfigData")["data-config"]) == {
        "vector_axis_label": "Size (bytes)", "fom_unit": "s"}
    assert "Chart unavailable" in "".join(markup.text)


@pytest.mark.parametrize("changed,unknown,summary", [
    (1, 1, ["1 difference", "1 unknown"]), (0, 0, ["Recorded versions match"]),
    (0, 2, ["2 unknown"]),
])
def test_version_panel_states_and_labels_are_escaped_and_collapsed(app, changed, unknown, summary):
    data = {"code": "sample", "current_system": {"system": "Current"},
            "future_system": {"system": "Future"}}
    context = build_estimated_detail_context(data)
    label = "<img src=x onerror=alert(1)>" + "long-name-" * 20
    context["version_check"] = {"commit": "a" * 40, "ref": "refs/heads/example",
                                "changed_count": changed, "unknown_count": unknown,
                                "rows": [{"name": label, "scope": "app", "component": "method",
                                          "recorded": "old", "reference": "new", "status": "different"}]
                                if changed else []}
    with app.test_request_context():
        html = render_template("estimated_detail.html", result=data, **context)
    markup = Markup(html)
    panel = next(attrs for tag, attrs in markup.tags if tag == "details"
                 and attrs.get("class") == "estimate-version-check")
    assert "open" not in panel
    text = "".join(markup.text)
    assert all(value in text for value in summary)
    if changed:
        assert label in text
        assert not any(tag == "img" and attrs.get("onerror") == "alert(1)" for tag, attrs in markup.tags)
    else:
        assert not any(attrs.get("class") == "estimate-version-table" for _, attrs in markup.tags)


def test_version_panel_is_absent_without_a_check(app):
    with app.test_request_context():
        html = render_template("_estimate_version_check.html", version_check=None)
    assert not any(tag == "details" for tag, _ in Markup(html).tags)
