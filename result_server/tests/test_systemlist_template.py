import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs(include_otp=False)


def test_systemlist_page_renders_summary_and_table():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )

    with app.test_request_context("/systemlist"):
        from flask import render_template

        html = render_template(
            "systemlist.html",
            systems_summary={
                "total_count": 2,
                "gpu_enabled_count": 1,
                "cpu_only_count": 1,
            },
            systems_info={
                "Fugaku": {
                    "name": "Fugaku",
                    "cpu_name": "A64FX",
                    "cpu_per_node": "1",
                    "cpu_cores": "48",
                    "gpu_name": "-",
                    "gpu_per_node": "-",
                    "memory": "32GB",
                },
                "MiyabiG": {
                    "name": "MiyabiG",
                    "cpu_name": "NVIDIA Grace CPU",
                    "cpu_per_node": "1",
                    "cpu_cores": "72",
                    "gpu_name": "NVIDIA Hopper H100 GPU",
                    "gpu_per_node": "1",
                    "memory": "120GB",
                },
            },
        )

    assert "Available Systems" in html
    assert "Connected systems registered in the portal." in html
    assert "Systems with GPU accelerators listed in" in html
    assert "systems-table" in html
    assert "systems-table-wrap" in html
    assert "Filter systems by name, CPU, GPU, or memory" in html
    assert "GPU-enabled" in html
    assert "CPU-only" in html
    assert "Hardware summaries are sourced from" in html
    assert "Fugaku" in html
    assert "MiyabiG" in html
