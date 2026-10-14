"""Optional visual checks using requirements-browser-tests.txt; no live service."""

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
from flask import render_template
from utils.estimated_detail_view import build_estimated_detail_context


class EstimateVersionsBrowserTests(unittest.TestCase):
    def test_collapsed_and_expanded_panel_on_desktop_and_mobile(self):
        app = build_portal_shell_app(templates_dir=str(ROOT / "result_server/templates"))
        result = {"code": "sample", "current_system": {"system": "Current"},
                  "future_system": {"system": "Future"}}
        context = build_estimated_detail_context(result)
        context["version_check"] = {
            "commit": "a" * 40, "ref": "refs/heads/example",
            "changed_count": 1, "unknown_count": 1,
            "rows": [
                {"scope": "future / sections / compute / candidate / predictor",
                 "component": "requested package", "name": "long-component-name-" * 5,
                 "recorded": "previous-version-" * 5, "reference": "candidate-version-" * 5,
                 "status": "different"},
                {"scope": "app", "component": "estimation method", "name": "sample",
                 "recorded": "Unknown", "reference": "declared", "status": "unknown"},
            ],
        }
        with app.test_request_context():
            html = render_template("estimated_detail.html", result=result, **context)
        client = app.test_client()

        def respond(route):
            url = urlsplit(route.request.url)
            self.assertEqual(url.hostname, "estimate.test")
            if url.path == "/preview":
                route.fulfill(body=html, content_type="text/html")
            else:
                response = client.get(url.path)
                route.fulfill(status=response.status_code, body=response.data,
                              content_type=response.content_type)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (1440, 390):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={"width": width, "height": 1000})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.route("**/*", respond)
                        page.goto("http://estimate.test/preview")
                        panel = page.locator(".estimate-version-check")
                        self.assertFalse(panel.evaluate("node => node.open"))
                        panel.locator("summary").click()
                        self.assertTrue(panel.evaluate("node => node.open"))
                        panel.scroll_into_view_if_needed()
                        box = panel.bounding_box()
                        self.assertGreaterEqual(box["x"], 0)
                        self.assertLessEqual(box["x"] + box["width"], width + 1)
                        self.assertTrue(panel.locator("td").evaluate_all(
                            "cells => cells.every(cell => cell.scrollWidth <= cell.clientWidth + 1)"))
                        if width == 390:
                            table_width = panel.locator("table").bounding_box()["width"]
                            self.assertAlmostEqual(panel.locator("td").first.bounding_box()["width"],
                                                   table_width, delta=2)
                        directory = os.environ.get("BK_VERSION_SCREENSHOT_DIR")
                        if directory:
                            Path(directory).mkdir(parents=True, exist_ok=True)
                            panel.screenshot(path=str(Path(directory) / f"version-check-{width}.png"))
                        self.assertEqual(errors, [])
                        page.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
