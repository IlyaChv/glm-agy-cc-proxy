#!/usr/bin/env python3
"""Run one self-contained task through Claude Code on the Z.AI GLM endpoint.

The Z.AI endpoint, key and model names are set only in the child's environment;
~/.claude/settings.json is neither read nor written. The brief goes in on stdin, the answer
comes out on stdout, the cost of the call on stderr. Design and measurements: GLM/README.md,
docs/adr/ADR-001, skills/glm/SKILL.md.

    python glm-run.py --dir <clean git repo> --prompt "<brief>"    (or --prompt-file <path>)

Exit codes: 0 success, 1 the worker failed or reported an error, 2 refused before any call,
3 timeout.
"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import workers_common as common  # noqa: E402

PROG = "glm-run"
common.utf8_stdio()

BASE_URL = "https://api.z.ai/api/anthropic"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".claude", "zai_api_key.txt")

# Model ids and the paired settings come from the Z.AI guide for Claude Code
# (docs.z.ai/devpack/tool/claude). "[1m]" selects the 1M-token context variant and only takes
# effect together with CLAUDE_CODE_AUTO_COMPACT_WINDOW.
GLM_SONNET = "glm-5.3[1m]"
GLM_OPUS = "glm-5.3[1m]"
GLM_HAIKU = "glm-5.3-flash[1m]"
AUTO_COMPACT_WINDOW = "1000000"
API_TIMEOUT_MS = "3000000"

# Claude Code's subagent tool has been called both names across versions. Deny both: an
# unrecognised name in --disallowed-tools is ignored, a missing one is a worker that fans out.
SUBAGENT_TOOLS = ["Task", "Agent"]

EXIT_CODES = (
    "exit codes: 0 success; 1 the worker failed or reported an error; 2 refused before any "
    "call (bad arguments, forbidden directory, dirty tree, bad prompt file, missing key or "
    "binary); 3 timeout"
)


def find_claude():
    """Absolute path to a claude executable subprocess can actually start.

    shutil.which("claude") returns the npm shim `claude.CMD`, which CreateProcess cannot
    execute without a shell, so the shim is resolved to the .exe it calls. The desktop app's
    copy is the fallback. A stub bin/claude.exe left by a blocked postinstall is a file, so it
    is selected and the child fails with no output.
    """
    override = os.environ.get("GLM_CLAUDE_BIN")
    if override:
        if os.path.isfile(override):
            return override
        # A pinned binary is pinned for a reason; falling back would run a different one.
        common.refuse(
            "glm-run: GLM_CLAUDE_BIN={} is not a file. Fix or unset it; refusing to fall "
            "back to another claude.".format(override)
        )

    candidates = []

    # The shim lives next to the node_modules tree that holds the real binary.
    shim = shutil.which("claude")
    if shim:
        prefix = os.path.dirname(shim)
        candidates.append(
            os.path.join(
                prefix, "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe"
            )
        )

    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidates.append(
            os.path.join(
                appdata, "npm", "node_modules", "@anthropic-ai", "claude-code",
                "bin", "claude.exe",
            )
        )
        # Desktop app: one directory per version, newest wins.
        root = os.path.join(appdata, "Claude", "claude-code")
        if os.path.isdir(root):
            def as_version(name):
                try:
                    return tuple(int(p) for p in name.split("."))
                except ValueError:
                    return (0,)

            for name in sorted(os.listdir(root), key=as_version, reverse=True):
                candidates.append(os.path.join(root, name, "claude.exe"))

    for path in candidates:
        if os.path.isfile(path):
            return path

    common.refuse(
        "glm-run: cannot find a claude executable.\n"
        "         Tell the human: it needs `npm install -g "
        "--allow-scripts=@anthropic-ai/claude-code @anthropic-ai/claude-code`\n"
        "         (see GLM/README.md; the postinstall matters: without it bin/claude.exe\n"
        "         is a stub), or GLM_CLAUDE_BIN set to the full path of a claude.exe."
    )


def read_key():
    """The Z.AI key, or refuse. Without it the child would spend the Anthropic subscription."""
    if not os.path.isfile(KEY_FILE):
        common.refuse(
            "glm-run: no Z.AI key at {}\n"
            "         Ask the human to create it (one token, one line); do not write it\n"
            "         yourself. Refusing to run: without a key the call would fall back\n"
            "         to the Anthropic subscription.".format(KEY_FILE)
        )
    with open(KEY_FILE, encoding="utf-8-sig") as fh:
        key = fh.read().strip()
    if not key:
        common.refuse("glm-run: the key file {} is empty".format(KEY_FILE))
    if len(key.split()) > 1:
        common.refuse(
            "glm-run: the key file {} holds whitespace in the middle - it should be "
            "one token on one line".format(KEY_FILE)
        )
    return key


def child_env(key):
    """The scrubbed parent environment plus the Z.AI routing, for this child only."""
    env = common.scrubbed_env()
    env["ANTHROPIC_BASE_URL"] = BASE_URL
    env["ANTHROPIC_AUTH_TOKEN"] = key
    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = GLM_SONNET
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = GLM_OPUS
    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = GLM_HAIKU
    env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = AUTO_COMPACT_WINDOW
    env["API_TIMEOUT_MS"] = API_TIMEOUT_MS
    # Second lock on fan-out; the tool is also denied by name on the command line.
    env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"] = "0"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


@dataclass(frozen=True)
class Policy:
    blanket: bool          # --dangerously-skip-permissions
    mode: Optional[str]    # --permission-mode, None when not passed
    no_tools: bool         # --tools ""
    can_write: bool        # the worker can change files
    guarded: bool          # run the clean-tree guard and the change report


def decide_policy(args):
    """What the flags grant the worker. Raises ValueError on a contradiction."""
    if args.no_tools and args.allow_shell:
        raise ValueError("--no-tools and --allow-shell contradict each other")
    if args.no_tools:
        blanket, mode = False, None
    elif args.allow_shell:
        blanket, mode = True, None
    else:
        blanket, mode = False, args.mode or "acceptEdits"
    can_write = blanket or mode in ("acceptEdits", "dontAsk")
    return Policy(blanket, mode, bool(args.no_tools), can_write, can_write and not args.force)


def build_cmd(exe, args, mode, blanket, no_tools, extra_dirs):
    cmd = [
        exe,
        "--print",
        "--output-format", "json",
        # Decided here, not in ~/.claude/settings.json, so the switcher's current
        # mode cannot change what this call does.
        "--setting-sources", "project,local",
        # No --mcp-config alongside it, so the child loads no MCP servers at all.
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--autocompact", AUTO_COMPACT_WINDOW,
    ]
    if args.model:
        cmd += ["--model", args.model]
    if args.effort:
        cmd += ["--effort", args.effort]
    if args.agent:
        cmd += ["--agent", args.agent]
    if extra_dirs:
        cmd += ["--add-dir"] + list(extra_dirs)

    if no_tools:
        # Empty string means "no tools at all" - a pure-reasoning call.
        cmd += ["--tools", ""]
    else:
        cmd += ["--disallowed-tools"] + SUBAGENT_TOOLS

    if blanket:
        cmd.append("--dangerously-skip-permissions")
    else:
        # mode is None under --no-tools, where there are no tools to permit and
        # the flag would be passed the literal string "None".
        if mode:
            cmd += ["--permission-mode", mode]
        # Nobody is there to answer a prompt. "none" denies instead of waiting,
        # which turns a would-be hang into a fast failure the JSON records under
        # permission_denials.
        cmd += ["--permission-prompts", "none"]
    return cmd


@dataclass(frozen=True)
class Outcome:
    code: int
    answer: str = ""    # written to stdout
    message: str = ""   # written to stderr last, when not empty


def classify_result(payload, raw, returncode):
    """Exit code, answer and closing message from the worker's payload, stdout and exit code."""
    if not raw:
        return Outcome(common.EXIT_FAILED, message=(
            "glm-run: the worker produced no output at all (exit {}). Read the stderr above. "
            "Two known causes: an auth or quota failure against {} (not yet observed - trust "
            "the stderr over this line), or a claude.exe that is the npm stub left by a "
            "blocked postinstall (claude --version fails).".format(returncode, BASE_URL)))
    if payload is None:
        return Outcome(common.EXIT_FAILED, message=(
            "glm-run: the worker returned no parseable JSON object (exit {}).\n{}".format(
                returncode, raw[:2000])))

    result = common.as_text(payload.get("result"))
    if payload.get("is_error") or payload.get("subtype") not in (None, "success"):
        return Outcome(common.EXIT_FAILED, result, (
            "glm-run: the worker reported failure (subtype={}, api_error_status={}).".format(
                payload.get("subtype"), payload.get("api_error_status"))))
    if returncode != 0:
        # The child can die after flushing a complete-looking payload; exit 0 only on success.
        return Outcome(common.EXIT_FAILED, result, (
            "glm-run: the worker exited {} despite reporting success. The answer above may "
            "be truncated; treat this run as failed.".format(returncode)))
    if not result.strip():
        return Outcome(common.EXIT_FAILED, message=(
            "glm-run: the worker exited 0 with an empty answer. Check the denials and "
            "stderr above before retrying."))
    warning = ("glm-run: warning: output contained invalid UTF-8; some characters were "
               "replaced" if "�" in result else "")
    return Outcome(common.EXIT_OK, result, warning)


def main():
    ap = argparse.ArgumentParser(
        prog="glm-run",
        description="Run one self-contained task through Claude Code on the Z.AI GLM "
                    "endpoint, without touching ~/.claude/settings.json.",
        epilog=EXIT_CODES,
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt", help="the brief, inline")
    src.add_argument("--prompt-file", help="UTF-8 file holding the brief (preferred for long ones)")
    ap.add_argument("--dir", default=".", help="working directory for the worker (default: cwd)")
    ap.add_argument(
        "--model",
        help="model for the child session. Leave unset to use the GLM default "
        "(the sonnet slot, " + GLM_SONNET + ").",
    )
    ap.add_argument(
        "--effort", choices=["low", "medium", "high", "xhigh", "max"],
        help="reasoning effort passed to the child",
    )
    ap.add_argument("--agent", help="custom agent for the child session")
    ap.add_argument(
        "--allow-shell",
        action="store_true",
        help="pass --dangerously-skip-permissions, letting the worker run shell "
        "commands. This removes every boundary except the clean-tree guard, and "
        "that guard only covers git-tracked files inside --dir and each --add-dir. "
        "Use only when the "
        "task needs a shell, and say so when reporting the result.",
    )
    ap.add_argument(
        "--no-tools",
        action="store_true",
        help="pure-reasoning prompt: --tools \"\", so the worker has no tools at all "
        "and cannot touch the filesystem. Skips the clean-tree check.",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="skip the clean-tree check. Does not skip the forbidden-directory check. "
        "It also suppresses the gitignored-paths note and the after-run change report, "
        "so check `git status` yourself.",
    )
    ap.add_argument("--timeout-min", type=int, default=10, help="default: 10")
    ap.add_argument(
        "--mode", choices=["acceptEdits", "plan", "dontAsk", "manual"],
        help="permission mode for the child; defaults to acceptEdits; ignored with "
        "--allow-shell or --no-tools",
    )
    ap.add_argument(
        "--add-dir", action="append",
        help="give the worker an additional workspace directory; repeatable. Each "
        "one must be a clean git repository, same as --dir",
    )
    args = ap.parse_args()

    if args.timeout_min <= 0:
        common.refuse("glm-run: --timeout-min must be positive, got {}".format(args.timeout_min))

    work_dir = os.path.abspath(args.dir)
    if not os.path.isdir(work_dir):
        common.refuse("glm-run: no such directory: " + work_dir)

    prompt = common.read_prompt(args.prompt, args.prompt_file, PROG)

    try:
        policy = decide_policy(args)
    except ValueError as exc:
        common.refuse("glm-run: {}".format(exc))

    # Unconditional, and before anything else: --force is about a dirty tree, not
    # about where the worker is allowed to work.
    # The child runs with cwd=work_dir, so a relative --add-dir means work_dir/<it>; resolve once.
    extra_dirs = [os.path.realpath(os.path.join(work_dir, e)) for e in args.add_dir or []]
    for d in [work_dir] + extra_dirs:
        common.check_dir_allowed(d, PROG, "GLM_ALLOWED_ROOTS")

    if policy.guarded:
        for d in [work_dir] + extra_dirs:
            common.check_clean_tree(d, PROG)
        for d in [work_dir] + extra_dirs:
            common.warn_about_ignored(d, PROG)

    key = read_key()
    cmd = build_cmd(find_claude(), args, policy.mode, policy.blanket, policy.no_tools, extra_dirs)
    return run(cmd, work_dir, prompt, key, extra_dirs, policy, args.timeout_min * 60 + 30)


def run(cmd, work_dir, prompt, key, extra_dirs, policy, hard_limit):
    dirs = [work_dir] + extra_dirs
    heads = {d: common.head_commit(d) for d in dirs} if policy.guarded else {}
    # The brief goes in on stdin: no command-line ceiling, no argv quoting, not in the
    # process list.
    try:
        returncode, out, err = common.run_worker(
            cmd, work_dir, child_env(key), hard_limit, PROG, input_text=prompt)
    except subprocess.TimeoutExpired:
        if policy.guarded:
            common.report_changes(dirs, heads, PROG)
        common.die(
            "glm-run: the worker did not return within {}s. Its own request timeout "
            "is {}ms, so a wall-clock overrun here usually means a stuck tool call "
            "rather than a slow model. Do not retry the same call unchanged; narrow "
            "it, or raise --timeout-min deliberately.".format(hard_limit, API_TIMEOUT_MS),
            common.EXIT_TIMEOUT,
        )

    common.echo_stderr(err, PROG)

    raw = (out or "").strip()
    payload = common.parse_payload(raw) if raw else None
    outcome = classify_result(payload, raw, returncode)

    if policy.guarded:
        common.report_changes(dirs, heads, PROG)

    if payload is not None:
        report_cost(payload, returncode)

        denials = payload.get("permission_denials")
        if isinstance(denials, list) and denials:
            names = [str(d.get("tool_name", d)) if isinstance(d, dict) else str(d)
                     for d in denials]
            sys.stderr.write(
                "glm-run: {} tool call(s) were denied rather than prompted for: {}. "
                "Re-run with --allow-shell if the task genuinely needs a shell, or "
                "narrow the brief. A denied Edit/Write on a path under .claude/ is "
                "expected: make those edits from the driver, not with --allow-shell.\n".format(
                    len(denials), ", ".join(names[:8])
                )
            )

        spawned = common.as_dict(payload.get("subagent_stats")).get("spawned")
        if spawned:
            sys.stderr.write(
                "glm-run: warning: the worker spawned {} subagent(s) despite the depth "
                "cap - the cap is not holding - report it to the human (driver: first "
                "line of your report).\n".format(spawned)
            )

    sys.stdout.write(outcome.answer)
    if outcome.message:
        sys.stderr.write(outcome.message + "\n")
    return outcome.code


def report_cost(payload, returncode):
    """One line of what the call cost, tokens first.

    total_cost_usd is Claude Code's own arithmetic over a price table with no GLM entry (the
    JSON marks it costBasis "unknown"), so it is labelled rather than read as a Z.AI charge.
    """
    usage = common.as_dict(payload.get("usage"))
    models = common.as_dict(payload.get("modelUsage"))
    which = ", ".join(sorted(str(m) for m in models)) or "?"
    basis = {str(m.get("costBasis")) for m in models.values() if isinstance(m, dict)}

    sys.stderr.write(
        "glm-run: model={} in={} out={} cache_read={} cache_write={} turns={} {:.0f}s\n".format(
            which,
            usage.get("input_tokens", "?"),
            usage.get("output_tokens", "?"),
            usage.get("cache_read_input_tokens", "?"),
            usage.get("cache_creation_input_tokens", "?"),
            payload.get("num_turns", "?"),
            common.as_number(payload.get("duration_ms")) / 1000.0,
        )
    )
    cost = payload.get("total_cost_usd")
    if cost is not None:
        note = " (costBasis unknown: priced from Claude Code's table, which has no " \
               "GLM entry - not a Z.AI charge)" if "unknown" in basis else ""
        sys.stderr.write("glm-run: total_cost_usd={}{}\n".format(cost, note))
    sys.stderr.write(
        "glm-run: exit={} session={}\n".format(returncode, payload.get("session_id", "?"))
    )


if __name__ == "__main__":
    sys.exit(main())
