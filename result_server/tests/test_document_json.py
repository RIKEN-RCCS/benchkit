"""Document write-boundary checks without application or live configuration."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.document_json import load_document_json


@pytest.mark.parametrize("raw", [
    '{"x":1,"x":1}', '{"x":1,"x":2}',
    '{"outer":[{"private-field":"private-value","private-field":"private-value"}]}',
    '{"x":1,"\\u0078":1}',
])
def test_rejects_duplicates_without_disclosing_members(raw):
    with pytest.raises(ValueError, match="^Duplicate JSON object member$"):
        load_document_json(raw)


@pytest.mark.parametrize("raw", [
    '{"FOM":1.23456789012345,"unknown":{"x":[1,null,true]}}',
    '{"a":{"x":1},"b":{"x":2}}', '{}',
])
def test_normal_decoding_is_unchanged(raw):
    assert load_document_json(raw) == json.loads(raw)


@pytest.mark.parametrize("args", [
    ["string", "x", "one", "string", "x", "one"],
    ["string", "x", "one", "json", "x", "2"],
    ["bad-kind", "x", "one"], ["string", "x"],
])
def test_shell_writer_rejects_invalid_fields_before_output(args):
    source = Path(__file__).resolve().parents[2] / "scripts/json_output.sh"
    result = subprocess.run(["bash", "-c", 'set -eu; source "$1"; shift; bk_json_object "$@"',
                             "contract", str(source), *args], capture_output=True)
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b""


def test_shell_writer_keeps_escaping_and_valid_values():
    source = Path(__file__).resolve().parents[2] / "scripts/json_output.sh"
    result = subprocess.run(["bash", "-c", 'set -eu; source "$1"; shift; bk_json_object "$@"',
        "contract", str(source), "string", 'quoted"key', "value\ntext", "json", "FOM", "1.25"],
        capture_output=True, check=True)
    assert json.loads(result.stdout) == {'quoted"key': "value\ntext", "FOM": 1.25}
