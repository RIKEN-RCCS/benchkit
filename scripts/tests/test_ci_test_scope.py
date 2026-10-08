import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ci_test_scope import full_tests, lightweight_edit, main, select_scope


class ScopeTests(unittest.TestCase):
    def test_documentation_allowlist(self):
        for path in ("README.md", "docs/ci.md", "programs/demo/README.md", "LICENSE"):
            with self.subTest(path=path):
                self.assertTrue(lightweight_edit(path, b"before", b"after"))
        for path in ("docs/tool.sh", "scripts/tests/fixture.md", "config/system.csv",
                     "requirements-result-server.txt", ".github/workflows/ci.yml"):
            with self.subTest(path=path):
                self.assertFalse(lightweight_edit(path, b"before", b"after"))

    def test_header_only(self):
        self.assertTrue(lightweight_edit("src/demo.cpp", b"// Old author\nint x;\n",
                                        b"// Original author\nint x;\n"))
        self.assertFalse(lightweight_edit("src/demo.cpp", b"// Old author\nint x;\n",
                                         b"// Original author\nint y;\n"))

    def test_line_numbers_are_observable(self):
        self.assertFalse(lightweight_edit("src/demo.cpp", b"// Old\nint x = __LINE__;\n",
                                         b"// New\n// Author\nint x = __LINE__;\n"))

    def test_unsafe_headers(self):
        for header in (b"// splice\\\n", b"// splice??/\n", b"// CRLF\r\n",
                       b"// invalid\xff\n", b"// NUL\x00\n"):
            with self.subTest(header=header):
                with self.assertRaises(ValueError):
                    lightweight_edit("src/demo.cpp", b"// old\nint x;\n", header + b"int x;\n")

    def test_manual_and_unknown_events_run_full(self):
        for event in ("workflow_dispatch", "unknown"):
            self.assertTrue(select_scope(event, {}, "a" * 40))
        self.assertTrue(select_scope("push", {"forced": True}, "a" * 40))
        self.assertTrue(select_scope("push", {"before": "b" * 40, "after": "c" * 40}, "a" * 40))

    def test_missing_event_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(Path(tmp) / "missing"),
                                         "GITHUB_OUTPUT": str(output)}):
                main()
            self.assertEqual(output.read_text(), "full=true\n")

    def test_non_object_event_runs_full(self):
        for event in (None, [], "invalid", 1):
            for name in ("push", "pull_request"):
                with self.subTest(name=name, event=event):
                    self.assertTrue(select_scope(name, event, "a" * 40))


class GitScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, old_cwd)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        Path("README.md").write_text("Before\n")
        Path("demo.cpp").write_text("// Old\nint x;\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_docs_and_header(self):
        Path("README.md").write_text("After\n")
        Path("demo.cpp").write_text("// New\nint x;\n")
        head = self.commit()
        self.assertFalse(full_tests(self.base, head))
        self.assertFalse(select_scope("pull_request", {"pull_request": {"base": {"sha": self.base}}}, head))
        self.assertFalse(select_scope("push", {"before": self.base, "after": head}, head))

    def test_mixed_code_changes(self):
        Path("README.md").write_text("After\n")
        Path("demo.cpp").write_text("// Old\nint y;\n")
        self.assertTrue(full_tests(self.base, self.commit()))

    def test_added_file(self):
        Path("NEW.md").write_text("new\n")
        self.assertTrue(full_tests(self.base, self.commit()))

    def test_deleted_file(self):
        Path("README.md").unlink()
        self.assertTrue(full_tests(self.base, self.commit()))

    def test_renamed_file(self):
        Path("README.md").rename("NEW.md")
        self.assertTrue(full_tests(self.base, self.commit()))

    def test_executable_file(self):
        Path("README.md").chmod(0o755)
        self.assertTrue(full_tests(self.base, self.commit()))

    def test_symlink(self):
        Path("README.md").unlink()
        Path("README.md").symlink_to("demo.cpp")
        self.assertTrue(full_tests(self.base, self.commit()))

    def test_unknown_history_and_empty_diff(self):
        self.assertTrue(full_tests(self.base, self.base))
        self.assertTrue(full_tests("0" * 40, self.base))
        self.assertTrue(full_tests("--help", self.base))

    def test_push_checks_all_commits(self):
        Path("demo.cpp").write_text("// Old\nint y;\n")
        self.commit()
        Path("README.md").write_text("After\n")
        self.assertTrue(full_tests(self.base, self.commit()))


if __name__ == "__main__":
    unittest.main()
