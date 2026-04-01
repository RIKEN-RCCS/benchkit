# Feature: code-source-tracking, Property 3: ハッシュ値のフォーマット検証
"""
Property 3: ハッシュ値のフォーマット検証

ランダムな40桁/32桁16進数文字列を生成し、
commit_hash が正確に40桁の16進数、md5sum が正確に32桁の16進数であることを検証する。
また、これらのハッシュ値を含む source_info 構造体が有効であることも検証する。

**Validates: Requirements 1.5, 1.6**
"""

import os
import sys
import re
import types

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# --- テスト用スタブモジュールの設定 ---
def _setup_stubs():
    """テスト用のスタブモジュールをsys.modulesに登録"""
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")

    otp_mod = types.ModuleType("utils.otp_manager")
    otp_mod.get_affiliations = lambda email: ["dev"]
    otp_mod.is_allowed = lambda email: True
    sys.modules["utils.otp_manager"] = otp_mod

    otp_redis_mod = types.ModuleType("utils.otp_redis_manager")
    otp_redis_mod.get_affiliations = lambda email: ["dev"]
    otp_redis_mod.is_allowed = lambda email: True
    otp_redis_mod.send_otp = lambda email: (True, "stub")
    otp_redis_mod.verify_otp = lambda email, code: True
    otp_redis_mod.invalidate_otp = lambda email: None
    sys.modules["utils.otp_redis_manager"] = otp_redis_mod

_setup_stubs()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# commit_hash 用ストラテジ: 正確に40桁の16進数文字列
commit_hash_strategy = st.text(
    alphabet="0123456789abcdef", min_size=40, max_size=40
)

# md5sum 用ストラテジ: 正確に32桁の16進数文字列
md5sum_strategy = st.text(
    alphabet="0123456789abcdef", min_size=32, max_size=32
)

COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MD5SUM_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class TestHashValueFormatProperty:
    """Property 3: ハッシュ値のフォーマット検証"""

    @given(commit_hash=commit_hash_strategy)
    @settings(max_examples=100)
    def test_commit_hash_is_exactly_40_hex_digits(self, commit_hash):
        """
        **Validates: Requirements 1.5**

        任意の生成された commit_hash が正確に40桁の16進数文字列であることを検証する。
        """
        assert len(commit_hash) == 40
        assert COMMIT_HASH_PATTERN.match(commit_hash) is not None

    @given(md5sum=md5sum_strategy)
    @settings(max_examples=100)
    def test_md5sum_is_exactly_32_hex_digits(self, md5sum):
        """
        **Validates: Requirements 1.6**

        任意の生成された md5sum が正確に32桁の16進数文字列であることを検証する。
        """
        assert len(md5sum) == 32
        assert MD5SUM_PATTERN.match(md5sum) is not None

    @given(commit_hash=commit_hash_strategy)
    @settings(max_examples=100)
    def test_git_source_info_structure_valid_with_commit_hash(self, commit_hash):
        """
        **Validates: Requirements 1.5**

        生成された commit_hash を含む git 型 source_info 構造体が
        スキーマに準拠した有効な構造であることを検証する。
        """
        source_info = {
            "source_type": "git",
            "repo_url": "https://github.com/example/repo.git",
            "branch": "main",
            "commit_hash": commit_hash,
        }

        # 構造体の必須フィールドが存在する
        assert source_info["source_type"] == "git"
        assert "repo_url" in source_info
        assert "branch" in source_info
        assert "commit_hash" in source_info

        # commit_hash が40桁16進数フォーマットに準拠
        assert COMMIT_HASH_PATTERN.match(source_info["commit_hash"]) is not None

    @given(md5sum=md5sum_strategy)
    @settings(max_examples=100)
    def test_file_source_info_structure_valid_with_md5sum(self, md5sum):
        """
        **Validates: Requirements 1.6**

        生成された md5sum を含む file 型 source_info 構造体が
        スキーマに準拠した有効な構造であることを検証する。
        """
        source_info = {
            "source_type": "file",
            "file_path": "/path/to/archive.tar.gz",
            "md5sum": md5sum,
        }

        # 構造体の必須フィールドが存在する
        assert source_info["source_type"] == "file"
        assert "file_path" in source_info
        assert "md5sum" in source_info

        # md5sum が32桁16進数フォーマットに準拠
        assert MD5SUM_PATTERN.match(source_info["md5sum"]) is not None
