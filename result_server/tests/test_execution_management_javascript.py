from pathlib import Path
import shutil
import subprocess

import pytest


def test_native_tab_navigation_and_legacy_anchors():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the JavaScript behavior test')
    result = subprocess.run([node, str(Path(__file__).with_name(
        'test_execution_management_navigation.js'))], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'tests 6' in result.stdout
