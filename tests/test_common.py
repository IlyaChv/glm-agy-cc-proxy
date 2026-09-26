"""lib/workers_common.py: payload parsing, directory guard, clean-tree guard, change report."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import workers_common as common  # noqa: E402

ROOTS_VAR = "WORKERS_TEST_ALLOWED_ROOTS"


def sh_git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   cwd=cwd, check=True, capture_output=True)


def temp_repo():
    d = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    sh_git(d.name, "init", "-q")
    sh_git(d.name, "commit", "-q", "--allow-empty", "-m", "init")
    return d


class ParsePayloadTest(unittest.TestCase):
    def test_parse_payload(self):
        cases = [
            ("whole document", '{"result": "ok"}', {"result": "ok"}),
            ("banner then JSON line", 'starting up...\nwarn: x\n{"result": "ok"}\n',
             {"result": "ok"}),
            ("indented JSON line", 'banner\n   {"a": 1}', {"a": 1}),
            ("trailing garbage", '{"result": "ok"}\ntrailing text', None),
            ("non-dict JSON", '[1, 2, 3]', None),
            ("JSON null", 'null', None),
            ("empty", '', None),
        ]
        for name, raw, expected in cases:
            with self.subTest(name):
                self.assertEqual(common.parse_payload(raw), expected)


class CheckDirAllowedTest(unittest.TestCase):
    def assertRefused(self, path):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as cm:
            common.check_dir_allowed(path, "test-run", ROOTS_VAR)
        self.assertEqual(cm.exception.code, common.EXIT_REFUSED)

    def test_refused_and_allowed_dirs(self):
        home = os.path.expanduser("~")
        refused = {
            "home": home,
            "home, case variant": home.swapcase(),
            "drive root": os.path.splitdrive(home)[0] + os.sep,
            "parent of home (C:\\Users)": os.path.dirname(home),
            "~/.claude/x": os.path.join(home, ".claude", "x"),
            "~/AppData (contains AppData/Roaming)": os.path.join(home, "AppData"),
            "UNC": r"\\localhost\C$\Users",
        }
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ROOTS_VAR, None)
            for name, path in refused.items():
                with self.subTest(refused=name):
                    self.assertRefused(path)
            with tempfile.TemporaryDirectory() as tmp:
                sub = os.path.join(tmp, "scratch")
                os.mkdir(sub)
                for name, path in {"%TEMP% subdir": sub, "project dir": str(ROOT)}.items():
                    with self.subTest(allowed=name):
                        common.check_dir_allowed(path, "test-run", ROOTS_VAR)


class CleanTreeTest(unittest.TestCase):
    def assertRefused(self, d):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as cm:
            common.check_clean_tree(d, "test-run")
        self.assertEqual(cm.exception.code, common.EXIT_REFUSED)

    def test_clean_passes_untracked_refuses_even_when_hidden(self):
        repo = temp_repo()
        with repo:
            common.check_clean_tree(repo.name, "test-run")
            os.mkdir(os.path.join(repo.name, "new"))
            Path(repo.name, "new", "file.txt").write_text("x", encoding="utf-8")
            self.assertRefused(repo.name)
            sh_git(repo.name, "config", "status.showUntrackedFiles", "no")
            self.assertRefused(repo.name)

    def test_non_repo_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertRefused(tmp)

    def test_report_changes_names_commits_and_untracked(self):
        repo = temp_repo()
        with repo:
            heads = {repo.name: common.head_commit(repo.name)}
            Path(repo.name, "committed.txt").write_text("x", encoding="utf-8")
            sh_git(repo.name, "add", "committed.txt")
            sh_git(repo.name, "commit", "-q", "-m", "by the worker")
            os.mkdir(os.path.join(repo.name, "made"))
            Path(repo.name, "made", "new.txt").write_text("x", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                common.report_changes([repo.name], heads, "test-run")
            text = err.getvalue()
            self.assertIn("HEAD moved", text)
            self.assertIn("made/new.txt", text)
            self.assertIn("git checkout . && git clean -fd", text)


if __name__ == "__main__":
    unittest.main()
