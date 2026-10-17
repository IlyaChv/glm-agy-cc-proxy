"""lib/workers_common.py: payload parsing, directory guard, pre-call snapshot, change report."""

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


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.snap_root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        patcher = mock.patch.object(common, "SNAPSHOT_ROOT", self.snap_root.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.snap_root.cleanup)

    def snapshot_and_report(self, d, heads, change):
        with contextlib.redirect_stderr(io.StringIO()):
            snaps = common.take_snapshots([d], "test-run")
        self.assertIsNotNone(snaps[d])
        change()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            common.report_changes(snaps, heads, "test-run")
        return snaps[d], err.getvalue()

    def revert(self, snap, d):
        base = ["--git-dir=" + snap, "--work-tree=" + d]
        sh_git(d, *base, "reset", "-q", "--hard", "HEAD")
        sh_git(d, *base, "clean", "-fdq")

    def test_non_repo_dir_is_snapshotted_reported_and_reverted(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "keep.txt").write_text("original", encoding="utf-8")

            def change():
                Path(d, "keep.txt").write_text("edited", encoding="utf-8")
                os.mkdir(os.path.join(d, "made"))
                Path(d, "made", "new.txt").write_text("x", encoding="utf-8")

            snap, text = self.snapshot_and_report(d, {}, change)
            self.assertIn("keep.txt", text)
            self.assertIn("made/new.txt", text)
            self.assertIn("reset -q --hard HEAD", text)
            self.revert(snap, d)
            self.assertEqual(Path(d, "keep.txt").read_text(encoding="utf-8"), "original")
            self.assertFalse(Path(d, "made").exists())

    def test_dirty_repo_keeps_its_own_changes_on_revert(self):
        repo = temp_repo()
        with repo:
            d = repo.name
            Path(d, "mine.txt").write_text("uncommitted work", encoding="utf-8")
            heads = {d: common.head_commit(d)}

            def change():
                Path(d, "committed.txt").write_text("x", encoding="utf-8")
                sh_git(d, "add", "committed.txt")
                sh_git(d, "commit", "-q", "-m", "by the worker")

            snap, text = self.snapshot_and_report(d, heads, change)
            self.assertIn("HEAD moved", text)
            self.assertIn("committed.txt", text)
            self.assertNotIn("mine.txt", text)
            self.revert(snap, d)
            self.assertEqual(Path(d, "mine.txt").read_text(encoding="utf-8"), "uncommitted work")
            self.assertFalse(Path(d, "committed.txt").exists())

    def test_no_change_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.txt").write_text("x", encoding="utf-8")
            _snap, text = self.snapshot_and_report(d, {}, lambda: None)
            self.assertIn("no files changed", text)


if __name__ == "__main__":
    unittest.main()
