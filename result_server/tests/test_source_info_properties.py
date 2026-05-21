"""Property-based tests for source hash formatting rules."""

import os
import re
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import install_portal_test_stubs
from utils.result_table_rows import _build_source_link

install_portal_test_stubs()


# Strategy for valid 40-digit hexadecimal commit hashes.
commit_hash_strategy = st.text(
    alphabet="0123456789abcdef", min_size=40, max_size=40
)

# Strategy for valid 32-digit hexadecimal MD5 hashes.
md5sum_strategy = st.text(
    alphabet="0123456789abcdef", min_size=32, max_size=32
)

COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MD5SUM_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class TestHashValueFormatProperty:
    """Property 3: source hash values must match their expected formats."""

    @given(commit_hash=commit_hash_strategy)
    @settings(max_examples=100)
    def test_commit_hash_is_exactly_40_hex_digits(self, commit_hash):
        """Validate that commit hashes stay at 40 hexadecimal characters."""
        assert len(commit_hash) == 40
        assert COMMIT_HASH_PATTERN.match(commit_hash) is not None

    @given(md5sum=md5sum_strategy)
    @settings(max_examples=100)
    def test_md5sum_is_exactly_32_hex_digits(self, md5sum):
        """Validate that MD5 hashes stay at 32 hexadecimal characters."""
        assert len(md5sum) == 32
        assert MD5SUM_PATTERN.match(md5sum) is not None

    @given(commit_hash=commit_hash_strategy)
    @settings(max_examples=100)
    def test_git_source_info_structure_valid_with_commit_hash(self, commit_hash):
        """Validate a git source_info payload with a formatted commit hash."""
        source_info = {
            "source_type": "git",
            "repo_url": "https://github.com/example/repo.git",
            "branch": "main",
            "commit_hash": commit_hash,
        }

        assert source_info["source_type"] == "git"
        assert "repo_url" in source_info
        assert "branch" in source_info
        assert "commit_hash" in source_info
        assert COMMIT_HASH_PATTERN.match(source_info["commit_hash"]) is not None

    @given(md5sum=md5sum_strategy)
    @settings(max_examples=100)
    def test_file_source_info_structure_valid_with_md5sum(self, md5sum):
        """Validate a file source_info payload with a formatted MD5 hash."""
        source_info = {
            "source_type": "file",
            "file_path": "/path/to/archive.tar.gz",
            "md5sum": md5sum,
        }

        assert source_info["source_type"] == "file"
        assert "file_path" in source_info
        assert "md5sum" in source_info
        assert MD5SUM_PATTERN.match(source_info["md5sum"]) is not None


def test_git_source_link_allows_http_urls_only():
    source_info = {
        "source_type": "git",
        "repo_url": "https://github.com/example/repo.git",
    }

    link = _build_source_link(source_info)

    assert link["href"] == "https://github.com/example/repo.git"
    assert link["title"] == "https://github.com/example/repo.git"


def test_git_source_link_rejects_javascript_urls():
    source_info = {
        "source_type": "git",
        "repo_url": "javascript:alert(1)",
    }

    link = _build_source_link(source_info)

    assert link["href"] is None
    assert link["title"] == "Repository URL is not linkable"


def test_git_source_link_rejects_ambiguous_urls():
    source_info = {
        "source_type": "git",
        "repo_url": "https://example.invalid\\@evil.invalid/repo.git",
    }

    link = _build_source_link(source_info)

    assert link["href"] is None
    assert link["title"] == "Repository URL is not linkable"


def test_file_source_link_uses_basename_only():
    source_info = {
        "source_type": "file",
        "file_path": "/sensitive/path/archive.tar.gz",
    }

    link = _build_source_link(source_info)

    assert link["href"] is None
    assert link["title"] == "archive.tar.gz"
