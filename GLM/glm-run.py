#!/usr/bin/env python3
"""Delegate a self-contained task to Claude Code running on the Z.AI GLM endpoint.

This is the delegation counterpart to `GLM/switch-claude.ps1`, and the opposite
approach. The switcher edits `~/.claude/settings.json` so that *every new* Claude
Code session speaks to Z.AI - which also breaks the desktop app, because it reads
`ANTHROPIC_DEFAULT_*_MODEL` from that file but ignores `ANTHROPIC_BASE_URL`
(measured 2026-09-14, see GLM/README.md). This wrapper instead starts one child
process with the Z.AI variables set **only in that child's environment** and
never touches `settings.json` at all. Nothing outside the call is affected, so
the orchestrating session keeps running on the Anthropic subscription.

It is the same shape as `~/.claude/bin/agy-run.py`: one brief in, one answer out,
the cost of the call on stderr, and a clean-tree guard so the worker's edits are
always revertible. The differences from agy-run are forced by the tool:

  - the brief goes in on **stdin**, not in argv. `claude --print` reads stdin when
    no positional prompt is given (verified 2026-09-14), which removes agy-run's
    32767-char command-line ceiling and its file-reference fallback entirely, and
    keeps the brief out of the process list.
  - the API key is read from `~/.claude/zai_api_key.txt` and passed in the child's
    environment. It is never an argument: argv is world-readable on Windows.
  - `--setting-sources project,local` makes the child skip `~/.claude/settings.json`.
    That is what decouples this wrapper from the switcher: whichever mode the
    switcher last left the file in, the child's endpoint is decided here and only
    here. It also means the child does not inherit the user's hooks or
    permission grants, which for a worker is the point.
  - MCP servers are silenced with `--strict-mcp-config` and no `--mcp-config`,
    skills with `--disable-slash-commands`, and session files with
    `--no-session-persistence`. A worker that loads the orchestrator's MCP
    servers pays for their tool definitions on every turn and can reach services
    the brief never mentioned.
  - subagent spawning is capped at depth 0 and the spawning tool is denied by
    name, so the worker cannot fan out further on its own.

Reading the cost report honestly: `total_cost_usd` is computed by Claude Code
from its own price table, which has no entry for GLM - the JSON says
`"costBasis":"unknown"`. The dollar figure is therefore **not** what Z.AI
charges; treat the token counts as the real number and the USD as a lower bound
of nothing in particular. This wrapper prints tokens first for that reason.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

# Windows makes sys.stdout/stderr inherit the console codepage (e.g. cp1251)
# whenever output isn't a real console - which is exactly what happens under
# redirection. Answers can contain any Unicode character, so a write here is one
# non-cp1251 character away from crashing or corrupting output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_URL = "https://api.z.ai/api/anthropic"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".claude", "zai_api_key.txt")

# Model ids and the two paired settings come from the Z.AI guide for Claude Code
# (docs.z.ai/devpack/tool/claude, manual-configuration section). The "[1m]"
# suffix is how Z.AI selects the 1M-token context variant, and it only takes
# effect together with CLAUDE_CODE_AUTO_COMPACT_WINDOW - confirmed by the probe
# on 2026-09-14, which reported contextWindow 1000000 in modelUsage.
GLM_SONNET = "glm-5.3[1m]"
GLM_OPUS = "glm-5.3[1m]"
GLM_HAIKU = "glm-5.3-flash[1m]"
AUTO_COMPACT_WINDOW = "1000000"
API_TIMEOUT_MS = "3000000"

# Claude Code's subagent tool has been called both names across versions. Deny
# both: an unrecognised name in --disallowed-tools is ignored, a missing one is a
# worker that quietly spawns its own fan-out on someone else's quota.
SUBAGENT_TOOLS = ["Task", "Agent"]

# Cap the child's stderr that gets copied into the caller's transcript. It
# carries whatever the worker's tools printed, and a transcript is copied,
# logged and shared - an unbounded paste is the cheapest way for something
# sensitive to end up in one.
MAX_STDERR_CHARS = 4000

# Directories a delegated call must never be pointed at, whatever the flags say.
# These hold credentials, agent configuration or application state. The
# permission entry that lets this script run unprompted matches the program path
# only, not its arguments, so --dir is unconstrained by the thing that decided
# not to ask the human. This is the floor under that.
#
# AppData is deliberately not blanket-forbidden: AppData/Local/Temp is where
# scratch working copies live, and delegating into one of those is normal.
FORBIDDEN_SUBPATHS = [
    ".gemini",
    ".claude",
    ".ssh",
    ".aws",
    ".gnupg",
    ".config",
    ".docker",
    "AppData/Roaming",
    "AppData/Local/Microsoft",
]


def find_claude():
    """Absolute path to a claude executable subprocess can actually start.

    shutil.which("claude") returns the npm shim `claude.CMD`, which CreateProcess
    cannot execute without a shell - so the shim is resolved to the .exe it calls
    rather than used directly. The desktop app's copy is the documented fallback
    for a machine where the standalone CLI was never installed, or where its
    postinstall was blocked and bin/claude.exe is still the stub that exits 1.
    """
    override = os.environ.get("GLM_CLAUDE_BIN")
    if override:
        if os.path.isfile(override):
            return override
        sys.stderr.write(
            "glm-run: warning: GLM_CLAUDE_BIN={} is not a file, ignoring it\n".format(override)
        )

    candidates = []

    # The shim lives next to the node_modules tree that holds the real binary,
    # so derive the exe from wherever npm actually put it.
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

    sys.exit(
        "glm-run: cannot find a claude executable.\n"
        "         Install the CLI with `npm install -g "
        "--allow-scripts=@anthropic-ai/claude-code @anthropic-ai/claude-code`\n"
        "         (the postinstall matters: without it bin/claude.exe is a stub),\n"
        "         or set GLM_CLAUDE_BIN to the full path of one."
    )


def read_key():
    """The Z.AI key, or exit. An absent key must never become a silent fallback.

    Without ANTHROPIC_AUTH_TOKEN the child would authenticate the ordinary way
    and spend the Anthropic subscription this wrapper exists to protect - while
    still looking like a successful delegated call in the transcript.
    """
    if not os.path.isfile(KEY_FILE):
        sys.exit(
            "glm-run: no Z.AI key at {}\n"
            "         Create it, or run GLM/switch-claude.bat and pick menu item 4.\n"
            "         Refusing to run: without a key the call would fall back to the\n"
            "         Anthropic subscription, which is the opposite of delegating.".format(
                KEY_FILE
            )
        )
    with open(KEY_FILE, encoding="utf-8-sig") as fh:
        key = fh.read().strip()
    if not key:
        sys.exit("glm-run: the key file {} is empty".format(KEY_FILE))
    if len(key.split()) > 1:
        sys.exit(
            "glm-run: the key file {} holds whitespace in the middle - it should be "
            "one token on one line".format(KEY_FILE)
        )
    return key


def git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )


def check_dir_allowed(work_dir):
    """Refuse a working directory that no delegated task should ever have.

    Not skippable with --force: --force exists to get past a dirty tree, which is
    a judgement call, whereas pointing a worker at a credential store is not.
    """
    home = os.path.abspath(os.path.expanduser("~"))
    real = os.path.realpath(work_dir)

    if real == home:
        sys.exit(
            "glm-run: refused, --dir is the home directory itself. Point it at a "
            "project, not at everything you own."
        )

    for rel in FORBIDDEN_SUBPATHS:
        forbidden = os.path.realpath(os.path.join(home, *rel.split("/")))
        if real == forbidden or real.startswith(forbidden + os.sep):
            sys.exit(
                "glm-run: refused, --dir is inside {}, which holds credentials or "
                "agent configuration.\n         No delegated task needs to work "
                "there. If you truly meant it, move the files out first.".format(rel)
            )

    # Optional per-machine narrowing, off unless the caller sets it. Semicolon
    # separated, since Windows paths contain colons.
    roots = os.environ.get("GLM_ALLOWED_ROOTS", "").strip()
    if roots:
        allowed = [os.path.realpath(r.strip()) for r in roots.split(";") if r.strip()]
        if not any(real == a or real.startswith(a + os.sep) for a in allowed):
            sys.exit(
                "glm-run: refused, --dir is outside GLM_ALLOWED_ROOTS.\n"
                "         dir:   {}\n         roots: {}".format(real, "; ".join(allowed))
            )


def warn_about_ignored(work_dir):
    """Name the gitignored files in --dir, which the clean-tree check cannot see.

    `git status --porcelain` omits ignored paths, so they are invisible before the
    run and unrestored by `git checkout .` after it.
    """
    res = git(["status", "--porcelain", "--ignored=matching"], work_dir)
    if res.returncode != 0:
        return
    ignored = [l[3:] for l in res.stdout.splitlines() if l.startswith("!! ")]
    if not ignored:
        return
    shown = ", ".join(ignored[:5])
    more = "" if len(ignored) <= 5 else " and {} more".format(len(ignored) - 5)
    sys.stderr.write(
        "glm-run: note: {} gitignored path(s) in --dir are outside the safety net "
        "- the worker can change them and `git checkout .` will not bring them "
        "back: {}{}\n".format(len(ignored), shown, more)
    )


def check_clean_tree(work_dir):
    """Edits are auto-approved, so require a clean git tree first.

    A clean tree turns any result the worker produces into `git checkout .`;
    without one there is nothing to undo a bad edit with. Note that
    `git status --porcelain` does not report gitignored files, so those stay
    invisible to this check - warn_about_ignored names them.
    """
    probe = git(["rev-parse", "--is-inside-work-tree"], work_dir)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        sys.exit(
            "glm-run: refused, {} is not a git repository. The worker runs with\n"
            "         edits auto-approved and can change files there with nothing to\n"
            "         revert. Run `git init`, or pass --no-tools, or --force.".format(work_dir)
        )
    status = git(["status", "--porcelain"], work_dir)
    if status.returncode != 0:
        sys.exit("glm-run: refused, `git status` failed:\n" + status.stderr)
    if status.stdout.strip():
        dirty = status.stdout.strip().splitlines()
        preview = "\n".join("         " + line for line in dirty[:10])
        more = "" if len(dirty) <= 10 else "\n         ... and {} more".format(len(dirty) - 10)
        sys.exit(
            "glm-run: refused, working tree is dirty - commit first so the delegated "
            "edits can be reverted (gitignored files are not shown here and are not "
            "reverted either):\n" + preview + more
        )


def report_changes(dirs):
    """Say what the worker actually touched.

    The clean-tree check was a point-in-time guarantee; this does not close the
    window between the check and the first write, but it does mean nobody has to
    go looking for what changed.
    """
    for d in dirs:
        after = git(["status", "--porcelain"], d)
        touched = [l for l in after.stdout.splitlines() if l.strip()]
        if not touched:
            continue
        shown = "\n".join("         " + t for t in touched[:15])
        more = "" if len(touched) <= 15 else "\n         ... and {} more".format(
            len(touched) - 15
        )
        sys.stderr.write(
            "glm-run: {} path(s) changed in {} - revert with `git checkout .` there "
            "if this is not what you wanted:\n{}{}\n".format(len(touched), d, shown, more)
        )


def child_env(key):
    """The parent's environment plus the Z.AI routing, for this child only.

    `~/.claude/settings.json` is not read, written or consulted anywhere in this
    script. That is the whole design: the switcher's failure mode is that it
    changes the endpoint for every future session including the desktop app's,
    and a per-process environment cannot do that.
    """
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = BASE_URL
    env["ANTHROPIC_AUTH_TOKEN"] = key
    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = GLM_SONNET
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = GLM_OPUS
    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = GLM_HAIKU
    env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = AUTO_COMPACT_WINDOW
    env["API_TIMEOUT_MS"] = API_TIMEOUT_MS
    # Keep the worker from fanning out onto the same quota behind our back. The
    # tool is also denied by name on the command line; this is the second lock.
    env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"] = "0"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    # An ANTHROPIC_API_KEY inherited from the parent would be sent to Z.AI, which
    # is both useless and a credential leak to a third party. Drop every
    # Anthropic auth variable we are not setting ourselves.
    for stale in ("ANTHROPIC_API_KEY", "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_MODEL",
                  "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_USE_BEDROCK",
                  "CLAUDE_CODE_USE_VERTEX"):
        env.pop(stale, None)
    return env


def build_cmd(exe, args, mode, blanket, no_tools):
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
    if args.add_dir:
        cmd += ["--add-dir"] + list(args.add_dir)

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


def main():
    ap = argparse.ArgumentParser(
        prog="glm-run",
        description="Run one self-contained task through Claude Code on the Z.AI GLM "
                    "endpoint, without touching ~/.claude/settings.json.",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt", help="the brief, inline")
    src.add_argument("--prompt-file", help="file holding the brief (preferred for long ones)")
    ap.add_argument("--dir", default=".", help="working directory for the worker (default: cwd)")
    ap.add_argument(
        "--model",
        help="model for the child session. Leave unset to use the GLM default "
        "(the sonnet slot, " + GLM_SONNET + ").",
    )
    ap.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--agent", help="custom agent for the child session")
    ap.add_argument(
        "--allow-shell",
        action="store_true",
        help="pass --dangerously-skip-permissions, letting the worker run shell "
        "commands. This removes every boundary except the clean-tree guard, and "
        "that guard only covers git-tracked files inside --dir. Use only when the "
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
        help="skip the clean-tree check. Does not skip the forbidden-directory check",
    )
    ap.add_argument("--timeout-min", type=int, default=10, help="default: 10")
    ap.add_argument(
        "--mode", choices=["acceptEdits", "plan", "dontAsk", "manual"],
        help="permission mode for the child; defaults to acceptEdits",
    )
    ap.add_argument(
        "--add-dir", action="append",
        help="give the worker an additional workspace directory; repeatable. Each "
        "one must be a clean git repository, same as --dir",
    )
    args = ap.parse_args()

    if args.timeout_min <= 0:
        sys.exit("glm-run: --timeout-min must be positive, got {}".format(args.timeout_min))

    work_dir = os.path.abspath(args.dir)
    if not os.path.isdir(work_dir):
        sys.exit("glm-run: no such directory: " + work_dir)

    if args.prompt_file:
        if not os.path.isfile(args.prompt_file):
            sys.exit("glm-run: no such prompt file: " + args.prompt_file)
        with open(args.prompt_file, encoding="utf-8") as fh:
            prompt = fh.read()
    else:
        prompt = args.prompt
    prompt = prompt.strip()
    if not prompt:
        sys.exit("glm-run: the prompt is empty")

    if args.no_tools and args.allow_shell:
        sys.exit("glm-run: --no-tools and --allow-shell contradict each other")

    if args.no_tools:
        blanket, mode = False, None
    elif args.allow_shell:
        blanket, mode = True, None
    else:
        blanket, mode = False, args.mode or "acceptEdits"

    # Unconditional, and before anything else: --force is about a dirty tree, not
    # about where the worker is allowed to work.
    extra_dirs = [os.path.abspath(e) for e in args.add_dir or []]
    for d in [work_dir] + extra_dirs:
        check_dir_allowed(d)

    can_write = blanket or mode in ("acceptEdits", "dontAsk")
    guarded = can_write and not args.force
    if guarded:
        for d in [work_dir] + extra_dirs:
            check_clean_tree(d)
        for d in [work_dir] + extra_dirs:
            warn_about_ignored(d)

    key = read_key()
    cmd = build_cmd(find_claude(), args, mode, blanket, args.no_tools)
    return run(cmd, work_dir, prompt, key, args, extra_dirs, guarded)


def kill_tree(proc):
    """taskkill takes the whole tree, which proc.kill() cannot.

    Every way taskkill can fail is invisible, so always fall back to killing the
    child ourselves: an orphaned worker keeps editing files in --dir with no
    reader on its pipe, and nothing in the output would say so.
    """
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10
        )
    except Exception as exc:
        sys.stderr.write("glm-run: taskkill failed ({}), killing the child only\n".format(exc))
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def echo_stderr(err):
    """Copy the child's stderr through, truncated in the middle.

    Truncated, not scrubbed: this is the worker's own tool output. Keep both ends
    - notices tend to lead, tracebacks to trail - and say how much was dropped.
    """
    if not err:
        return
    if len(err) <= MAX_STDERR_CHARS:
        sys.stderr.write(err)
        return
    half = MAX_STDERR_CHARS // 2
    sys.stderr.write(
        err[:half]
        + "\n... glm-run: {} chars of worker stderr omitted ...\n".format(
            len(err) - MAX_STDERR_CHARS
        )
        + err[-half:]
    )


def run(cmd, work_dir, prompt, key, args, extra_dirs, guarded):
    # The brief goes in on stdin. `claude --print` reads it there when no
    # positional prompt is given, which means no command-line length ceiling, no
    # Windows argv quoting to corrupt it, and no brief visible in the process
    # list.
    proc = subprocess.Popen(
        cmd,
        cwd=work_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(key),
    )

    hard_limit = args.timeout_min * 60 + 30
    try:
        out, err = proc.communicate(input=prompt, timeout=hard_limit)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        if guarded:
            report_changes([work_dir] + extra_dirs)
        sys.exit(
            "glm-run: the worker did not return within {}s. Its own request timeout "
            "is {}ms, so a wall-clock overrun here usually means a stuck tool call "
            "rather than a slow model. Do not retry the same call unchanged; narrow "
            "it, or raise --timeout-min deliberately.".format(hard_limit, API_TIMEOUT_MS)
        )

    echo_stderr(err)

    raw = (out or "").strip()
    if not raw:
        sys.exit(
            "glm-run: the worker produced no output at all (exit {}). Check the "
            "stderr above - an auth failure against {} looks like this.".format(
                proc.returncode, BASE_URL
            )
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        if start == -1:
            sys.exit(
                "glm-run: the worker returned no JSON (exit {}).\n{}".format(
                    proc.returncode, raw[:2000]
                )
            )
        try:
            payload = json.loads(raw[start:])
        except json.JSONDecodeError as exc:
            sys.exit("glm-run: cannot parse the worker's output ({}):\n{}".format(exc, raw[:2000]))

    # `null`, a list or a bare number all parse as valid JSON, and every field
    # read below would raise on them. Fail with the diagnostic instead.
    if not isinstance(payload, dict):
        sys.exit(
            "glm-run: the worker returned JSON that is not an object (exit {}).\n{}".format(
                proc.returncode, raw[:2000]
            )
        )

    if guarded:
        report_changes([work_dir] + extra_dirs)

    report_cost(payload, proc.returncode)

    denials = payload.get("permission_denials") or []
    if denials:
        names = []
        for d in denials:
            if isinstance(d, dict):
                names.append(str(d.get("tool_name", d)))
            else:
                names.append(str(d))
        sys.stderr.write(
            "glm-run: {} tool call(s) were denied rather than prompted for: {}. "
            "Re-run with --allow-shell if the task genuinely needs a shell, or "
            "narrow the brief.\n".format(len(denials), ", ".join(names[:8]))
        )

    spawned = (payload.get("subagent_stats") or {}).get("spawned")
    if spawned:
        sys.stderr.write(
            "glm-run: warning: the worker spawned {} subagent(s) despite the depth "
            "cap - the cap is not holding, tell the human.\n".format(spawned)
        )

    result = payload.get("result", "")
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False)

    if payload.get("is_error") or payload.get("subtype") not in (None, "success"):
        sys.stdout.write(result)
        sys.stderr.write(
            "glm-run: the worker reported failure (subtype={}, api_error_status={}).\n".format(
                payload.get("subtype"), payload.get("api_error_status")
            )
        )
        return 1

    if proc.returncode != 0:
        # A payload can be complete and its answer still truncated if the child
        # died after flushing stdout. This contract is "exit 0 only on success",
        # so a dead child is a failure even when the envelope says otherwise. The
        # answer is printed first, so nothing is lost by failing here.
        sys.stdout.write(result)
        sys.stderr.write(
            "glm-run: the worker exited {} despite reporting success. The answer "
            "above may be truncated; treat this run as failed.\n".format(proc.returncode)
        )
        return 1

    if "�" in result:
        sys.stderr.write(
            "glm-run: warning: output contained invalid UTF-8; some characters were "
            "replaced\n"
        )

    if not result.strip():
        sys.stderr.write(
            "glm-run: the worker exited 0 with an empty answer. Check the denials "
            "and stderr above before retrying.\n"
        )
        return 1

    sys.stdout.write(result)
    return 0


def report_cost(payload, returncode):
    """One line of what the call cost, tokens first.

    total_cost_usd is Claude Code's own arithmetic over a price table with no GLM
    entry - the JSON marks it costBasis "unknown". It is reported because a
    relative figure is still useful across calls, and labelled because treating
    it as a Z.AI invoice would be wrong.
    """
    usage = payload.get("usage") or {}
    models = payload.get("modelUsage") or {}
    which = ", ".join(sorted(models)) or "?"
    basis = {m.get("costBasis") for m in models.values() if isinstance(m, dict)}

    sys.stderr.write(
        "glm-run: model={} in={} out={} cache_read={} cache_write={} turns={} {:.0f}s\n".format(
            which,
            usage.get("input_tokens", "?"),
            usage.get("output_tokens", "?"),
            usage.get("cache_read_input_tokens", "?"),
            usage.get("cache_creation_input_tokens", "?"),
            payload.get("num_turns", "?"),
            (payload.get("duration_ms") or 0) / 1000.0,
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
