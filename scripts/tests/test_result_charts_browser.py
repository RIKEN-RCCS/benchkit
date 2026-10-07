"""Optional browser checks; see requirements-browser-tests.txt and docs/ci.md."""

import copy
from importlib.metadata import version
import os
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "result_server"))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs()
from flask import render_template, render_template_string
from utils.result_detail_view import build_result_detail_context
from utils.result_compare_view import build_result_compare_context


RESULT = {
    "code": "example", "system": "Example", "Exp": "sample", "FOM": 2, "FOM_unit": "s",
    "metrics": {"vector": {
        "x_axis": {"name": "Input size", "unit": "bytes"},
        "table": {"columns": ["Size", "Throughput", "Latency"],
                  "rows": [[1, 2, 8], [10, 4, 6], [100, 8, 3]]},
    }},
}


class ResultChartsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        print(f"Browser test runtime: Playwright {version('playwright')}, Chromium {cls.browser.version}", flush=True)
        cls.app = build_portal_shell_app(templates_dir=str(ROOT / "result_server/templates"))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 1000})
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def load(self, html, *, blocked=False):
        client = self.app.test_client()

        def respond(route):
            url = urlsplit(route.request.url)
            self.assertEqual(url.hostname, "charts.test")
            if url.path == "/preview":
                route.fulfill(body=html, content_type="text/html")
            elif blocked:
                route.abort()
            else:
                with client.get(url.path) as response:
                    route.fulfill(status=response.status_code, body=response.data,
                                  content_type=response.content_type)

        self.page.route("**/*", respond)
        self.page.goto("http://charts.test/preview")

    def detail(self, result):
        with self.app.test_request_context():
            return render_template("result_detail.html", result=result, quality={},
                                   **build_result_detail_context(result, {}))

    def screenshot(self, name):
        directory = os.environ.get("BK_CHART_SCREENSHOT_DIR")
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            self.page.locator(".chart-container").first.screenshot(path=str(Path(directory) / name))

    def chart_fixture(self, vector):
        # Exercise defensive plotting separately from the numeric data-table contract.
        with self.app.test_request_context():
            return render_template_string('''
                {% include "_chart_page_styles.html" %}
                <div class="chart-container"><div id="vectorChart"></div></div>
                <div id="vectorData" data-vector='{{ vector | tojson }}'></div>
                <div id="chartFallback" hidden>Chart unavailable</div>
                <script defer src="{{ url_for('static', filename='js/result_charts.js') }}"></script>
            ''', vector=vector)

    def test_detail_log_axis_legend_tooltip_and_resize(self):
        self.load(self.detail(RESULT))
        points = self.page.locator("#vectorChart circle")
        self.assertEqual(points.count(), 6)
        positions = points.evaluate_all("points => points.slice(0, 3).map(p => +p.getAttribute('cx'))")
        self.assertAlmostEqual(positions[1] - positions[0], positions[2] - positions[1])
        points.first.focus()
        self.assertIn("Throughput: 1 / 2", self.page.locator(".result-chart-value").inner_text())
        self.screenshot("result-chart-desktop.png")
        self.page.get_by_label("Throughput", exact=True).uncheck()
        self.assertEqual(points.count(), 3)
        self.page.get_by_label("Latency", exact=True).uncheck()
        self.assertIn("No plottable data", self.page.locator("#vectorChart").inner_text())
        self.page.get_by_label("Throughput", exact=True).check()
        self.page.set_viewport_size({"width": 390, "height": 1000})
        self.page.wait_for_function("Math.abs(document.querySelector('svg.result-chart-plot').viewBox.baseVal.width - document.getElementById('vectorChart').clientWidth) < 1")
        chart = self.page.locator("#vectorChart").bounding_box()
        self.assertLessEqual(chart["x"] + chart["width"], 390)
        self.screenshot("result-chart-mobile.png")
        self.assertFalse(self.page.locator("#chartFallback").is_visible())

    def test_invalid_and_missing_values_do_not_become_zero_or_connect_gaps(self):
        result = copy.deepcopy(RESULT)
        table = result["metrics"]["vector"]["table"]
        table["columns"] = ["Size", "<img src=x onerror=alert(1)>"]
        table["rows"] = [[0, 100], [1, -2], [10, None], [100, 0], [1000, ""], [-1, 5]]
        self.load(self.chart_fixture(result["metrics"]["vector"]))
        self.assertEqual(self.page.locator("#vectorChart circle").count(), 2)
        self.assertEqual(self.page.locator("#vectorChart img").count(), 0)
        paths = self.page.locator("#vectorChart path[stroke-width='2']")
        self.assertEqual(paths.first.get_attribute("d").count("M"), 2)
        self.assertNotIn("NaN", self.page.locator("#vectorChart svg").inner_html())

    def test_compare_multiple_series_and_timeline(self):
        results = [{"timestamp": f"2030-01-0{i + 1} 12:00:00", "data": copy.deepcopy(RESULT)} for i in range(3)]
        results[0]["data"]["FOM"] = 0
        results[1]["data"]["FOM"] = None
        with self.app.test_request_context():
            html = render_template("result_compare.html", **build_result_compare_context(results))
        self.load(html)
        self.assertEqual(self.page.locator("#compareVectorChart circle").count(), 18)
        self.assertEqual(self.page.locator("#fomTimelineChart circle").count(), 2)
        self.screenshot("result-overlay-desktop.png")
        self.page.set_viewport_size({"width": 390, "height": 1000})
        self.page.wait_for_function("Math.abs(document.querySelector('#compareVectorChart svg').viewBox.baseVal.width - document.getElementById('compareVectorChart').clientWidth) < 1")
        self.screenshot("result-overlay-mobile.png")

    def test_empty_and_single_point(self):
        result = copy.deepcopy(RESULT)
        result["metrics"]["vector"]["table"]["rows"] = [[10, 0, None]]
        self.load(self.chart_fixture(result["metrics"]["vector"]))
        self.assertEqual(self.page.locator("#vectorChart circle").count(), 1)
        self.assertNotIn("NaN", self.page.locator("#vectorChart svg").inner_html())
        self.page.get_by_label("Throughput", exact=True).uncheck()
        self.assertIn("No plottable data", self.page.locator("#vectorChart").inner_text())

    def test_asset_failure_keeps_data_table(self):
        self.load(self.detail(RESULT), blocked=True)
        self.assertTrue(self.page.locator("#chartFallback").is_visible())
        self.assertIn("Vector Metrics - Data Table", self.page.locator("body").inner_text())


if __name__ == "__main__":
    unittest.main()
