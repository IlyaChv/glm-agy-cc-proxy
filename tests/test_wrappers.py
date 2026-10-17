"""GLM/glm-run.py and AGY/agy-run.py without the real CLIs: policy, command, result, timeout."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import workers_common as common  # noqa: E402


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


glm = load("glm_run", "GLM/glm-run.py")
agy = load("agy_run", "AGY/agy-run.py")

SECRET = "zai-test-key-not-real"


def glm_args(**kw):
    base = dict(no_tools=False, allow_shell=False, mode=None, force=False,
                model=None, effort=None, agent=None)
    base.update(kw)
    return Namespace(**base)


def agy_args(**kw):
    base = dict(no_tools=False, allow_shell=False, mode=None, no_sandbox=False, force=False,
                model="m", effort=None, agent=None, timeout_min=5, prompt_file=None)
    base.update(kw)
    return Namespace(**base)


def pairs(cmd):
    return list(zip(cmd, cmd[1:]))


class GlmBuildCmdTest(unittest.TestCase):
    def test_flag_table(self):
        for name, kw in {"default": {}, "--no-tools": {"no_tools": True},
                         "--allow-shell": {"allow_shell": True}}.items():
            with self.subTest(name):
                args = glm_args(**kw)
                p = glm.decide_policy(args)
                cmd = glm.build_cmd("claude.exe", args, p.mode, p.blanket, p.no_tools, [])
                skip = "--dangerously-skip-permissions" in cmd
                if name == "default":
                    self.assertIn(("--permission-mode", "acceptEdits"), pairs(cmd))
                    self.assertIn(("--permission-prompts", "none"), pairs(cmd))
                    self.assertIn(("--disallowed-tools", "Task"), pairs(cmd))
                    self.assertFalse(skip)
                    self.assertNotIn("--tools", cmd)
                elif name == "--no-tools":
                    self.assertIn(("--tools", ""), pairs(cmd))
                    self.assertNotIn("--permission-mode", cmd)
                    self.assertNotIn("--disallowed-tools", cmd)
                    self.assertFalse(skip)
                else:
                    self.assertTrue(skip)
                    self.assertNotIn("--permission-mode", cmd)
                    self.assertNotIn("--permission-prompts", cmd)
                    self.assertIn(("--disallowed-tools", "Task"), pairs(cmd))


class DecidePolicyTest(unittest.TestCase):
    def test_glm_truth_table(self):
        # flags -> (blanket, mode, can_write, guarded)
        table = [
            ({}, (False, "acceptEdits", True, True)),
            ({"force": True}, (False, "acceptEdits", True, False)),
            ({"mode": "plan"}, (False, "plan", False, False)),
            ({"mode": "dontAsk"}, (False, "dontAsk", True, True)),
            ({"mode": "manual"}, (False, "manual", False, False)),
            ({"no_tools": True}, (False, None, False, False)),
            ({"allow_shell": True}, (True, None, True, True)),
            ({"allow_shell": True, "force": True}, (True, None, True, False)),
        ]
        for kw, expected in table:
            with self.subTest(kw):
                p = glm.decide_policy(glm_args(**kw))
                self.assertEqual((p.blanket, p.mode, p.can_write, p.guarded), expected)
        with self.assertRaises(ValueError):
            glm.decide_policy(glm_args(no_tools=True, allow_shell=True))

    def test_agy_truth_table(self):
        # flags -> (blanket, mode, sandbox, can_write, guarded)
        table = [
            ({}, (False, "accept-edits", True, True, True)),
            ({"no_sandbox": True}, (False, "accept-edits", False, True, True)),
            ({"force": True}, (False, "accept-edits", True, True, False)),
            ({"mode": "plan"}, (False, "plan", True, False, False)),
            ({"allow_shell": True}, (True, None, False, True, True)),
            ({"no_tools": True}, (False, "plan", True, False, False)),
            ({"no_tools": True, "mode": "plan"}, (False, "plan", True, False, False)),
        ]
        for kw, expected in table:
            with self.subTest(kw):
                p = agy.decide_policy(agy_args(**kw))
                self.assertEqual((p.blanket, p.mode, p.sandbox, p.can_write, p.guarded),
                                 expected)
        for kw in ({"allow_shell": True}, {"mode": "accept-edits"}, {"no_sandbox": True}):
            with self.subTest(contradiction=kw), self.assertRaises(ValueError):
                agy.decide_policy(agy_args(no_tools=True, **kw))
        # --no-tools reaches agy as a read-only call.
        args = agy_args(no_tools=True)
        p = agy.decide_policy(args)
        cmd = agy.build_cmd("agy.exe", "q", args, p.mode, p.sandbox, p.blanket, [])
        self.assertIn("--sandbox", cmd)
        self.assertIn(("--mode", "plan"), pairs(cmd))
        self.assertNotIn("--dangerously-skip-permissions", cmd)


class GlmMainTest(unittest.TestCase):
    """main() with the key reader, binary lookup and worker stubbed."""

    def run_main(self, argv, run_worker):
        with mock.patch.object(sys, "argv", ["glm-run"] + argv), \
                mock.patch.object(glm, "read_key", return_value=SECRET), \
                mock.patch.object(glm, "find_claude", return_value="C:/fake/claude.exe"), \
                mock.patch.object(common, "run_worker", run_worker), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return glm.main()

    def test_env_scrubbed_and_key_never_in_argv(self):
        seen = {}

        def fake_worker(cmd, cwd, env, hard_limit, prog, input_text=None):
            seen.update(cmd=cmd, env=env)
            return 0, json.dumps({"result": "ok", "subtype": "success"}), ""

        inherited = {"ANTHROPIC_API_KEY": "host-key", "ANTHROPIC_BASE_URL": "https://host",
                     "CLAUDE_CODE_ENTRYPOINT": "claude-desktop", "CLAUDECODE": "1",
                     "KEEP_ME": "1"}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, inherited):
            rc = self.run_main(["--dir", d, "--no-tools", "--prompt", "hi"], fake_worker)
        self.assertEqual(rc, 0)
        env = seen["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDE_CODE_ENTRYPOINT", env)
        self.assertNotIn("CLAUDECODE", env)
        self.assertEqual(env["KEEP_ME"], "1")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], glm.BASE_URL)
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], SECRET)
        self.assertEqual(env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"], "0")
        self.assertFalse(any(SECRET in part for part in seen["cmd"]))
        self.assertNotIn(SECRET, " ".join(seen["cmd"]))
        with mock.patch.dict(os.environ, inherited):
            agy_env = common.scrubbed_env()
        self.assertFalse(any(k.startswith(("ANTHROPIC_", "CLAUDE_CODE_")) for k in agy_env))

    def test_relative_add_dir_checked_as_passed(self):
        checked, seen = [], {}
        real_check = common.check_dir_allowed

        def record(path, prog, roots_var):
            checked.append(path)
            return real_check(path, prog, roots_var)

        def fake_worker(cmd, cwd, env, hard_limit, prog, input_text=None):
            seen["cmd"] = cmd
            return 0, json.dumps({"result": "ok"}), ""

        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "extra"))
            with mock.patch.object(common, "check_dir_allowed", record):
                rc = self.run_main(["--dir", d, "--add-dir", "extra", "--force",
                                    "--prompt", "hi"], fake_worker)
        self.assertEqual(rc, 0)
        passed = seen["cmd"][seen["cmd"].index("--add-dir") + 1]
        self.assertEqual(checked[1], passed)
        self.assertEqual(passed, os.path.realpath(os.path.join(d, "extra")))


class AgyWebGrantsTest(unittest.TestCase):
    def test_grants_added_once_and_rest_of_file_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            Path(path).write_text(json.dumps(
                {"model": "m", "permissions": {"allow": ["read_file(*)"], "deny": ["x"]}}),
                encoding="utf-8")
            agy.ensure_web_grants(path)
            agy.ensure_web_grants(path)
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(data["model"], "m")
            self.assertEqual(data["permissions"]["deny"], ["x"])
            self.assertEqual(data["permissions"]["allow"], ["read_file(*)"] + agy.WEB_GRANTS)

    def test_missing_file_warns_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                agy.ensure_web_grants(path)
            self.assertIn("could not grant web access", err.getvalue())
            self.assertFalse(os.path.exists(path))


class ClassifyResultTest(unittest.TestCase):
    def test_glm(self):
        ok = {"result": "answer", "subtype": "success"}
        cases = [
            ("is_error", {"result": "boom", "is_error": True}, 0, 1, "boom", "reported failure"),
            ("error subtype", {"result": "", "subtype": "error_max_turns"}, 0, 1, "",
             "reported failure"),
            ("rc!=0 with answer", ok, 1, 1, "answer", "despite reporting success"),
            ("empty result", {"result": "  "}, 0, 1, "", "empty answer"),
            ("null result", {"result": None}, 0, 1, "", "empty answer"),
            ("success", ok, 0, 0, "answer", ""),
        ]
        for name, payload, rc, code, answer, message in cases:
            with self.subTest(name):
                out = glm.classify_result(payload, json.dumps(payload), rc)
                self.assertEqual((out.code, out.answer), (code, answer))
                self.assertIn(message, out.message)
        self.assertIn("no output at all", glm.classify_result(None, "", 1).message)
        self.assertIn("no parseable JSON", glm.classify_result(None, "garbage", 0).message)

    def test_agy(self):
        denial = 'jetski: no output produced - a tool required the "command" permission'
        cases = [
            ("status error", {"status": "ERROR", "error": "bad"}, 0, "", None, False,
             1, "", "agy-run: bad"),
            ("rc!=0 with answer", {"status": "SUCCESS", "response": "partial"}, 2, "", None,
             False, 1, "partial", "despite reporting SUCCESS"),
            ("empty + denial", {"status": "SUCCESS", "response": ""}, 0, denial, None, False,
             1, "", 'denied "command"'),
            ("empty under --allow-shell", {"status": "SUCCESS", "response": None}, 0, denial,
             None, True, 1, "", "fully auto-approved"),
            ("CANNOT READ BRIEF", {"status": "SUCCESS", "response": "CANNOT READ BRIEF"}, 0, "",
             "C:/b.md", False, 1, "", "could not read the brief at C:/b.md"),
            ("success", {"status": "SUCCESS", "response": "done"}, 0, "", None, False,
             0, "done", ""),
        ]
        for name, payload, rc, err, ref, blanket, code, answer, message in cases:
            with self.subTest(name):
                out = agy.classify_result(payload, json.dumps(payload), rc, err, ref, blanket)
                self.assertEqual((out.code, out.answer), (code, answer))
                self.assertIn(message, out.message)
        self.assertEqual(agy.classify_result(None, "", 0, "", None, False).code, 1)

    def test_cost_lines_survive_malformed_payload(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            glm.report_cost({"usage": None, "modelUsage": ["x"], "duration_ms": "slow",
                             "total_cost_usd": 0.1}, 0)
            agy.report_cost({"usage": [], "duration_seconds": None, "model": "gemini-x"}, "req")
            agy.report_cost({"usage": None, "model": None}, "requested-model")
        text = err.getvalue()
        self.assertIn("glm-run: model=? in=?", text)
        self.assertIn("model=gemini-x", text)
        self.assertIn("model=requested-model", text)


class TimeoutTest(unittest.TestCase):
    def test_sleeping_child_is_killed_and_exit_is_3(self):
        started = []
        real_popen = subprocess.Popen

        def spy(*a, **kw):
            proc = real_popen(*a, **kw)
            started.append(proc)
            return proc

        cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
        policy = glm.decide_policy(glm_args(no_tools=True))
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(subprocess, "Popen", spy), \
                contextlib.redirect_stderr(io.StringIO()) as err, \
                self.assertRaises(SystemExit) as cm:
            glm.run(cmd, d, "brief", SECRET, [], policy, hard_limit=1)
        self.assertEqual(cm.exception.code, common.EXIT_TIMEOUT)
        self.assertIsNotNone(started[0].poll(), "the sleeping child is still running")
        self.assertLess(time.monotonic() - t0, 30)
        self.assertIn("did not return within 1s", err.getvalue())


if __name__ == "__main__":
    unittest.main()
