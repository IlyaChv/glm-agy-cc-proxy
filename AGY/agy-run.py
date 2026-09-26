#!/usr/bin/env python3
"""Delegate a self-contained task to the Antigravity CLI (agy) in headless mode.

Claude Code stays the orchestrator on the Anthropic subscription; this hands one
brief to agy, which runs on the Google AI Pro quota, and returns its answer plus
its token usage.

Why a wrapper instead of calling `agy -p` directly:
  - pins --output-format json and --print-timeout, so a hung call fails fast
    instead of eating the default 5 minutes silently;
  - passes the prompt as a single argv element, so quotes and newlines survive
    (Windows PowerShell 5.1 mangles them when calling a native exe). The brief
    is therefore visible in the process list to any process on this machine
    while the call runs; --prompt-file does not change that - its content is
    still passed in argv unless it exceeds the ceiling - so nothing secret
    goes in a brief;
  - reports usage, so the caller can see a call cost ~17k input tokens as the
    floor, ~44k input to create one file and stop before burning the quota blind;
  - exits non-zero when agy reports failure OR returns an empty answer, which is
    what an auto-denied tool call looks like: status SUCCESS, response "";
  - refuses to run on a dirty or non-git tree, which is the only undo for
    edits, since accept-edits and --allow-shell both write without asking (--force skips
    this check while leaving tools on). The guarantee covers the git-tracked
    files inside --dir and --add-dir only: nothing confines agy's file tools to
    those directories, so edits outside them are neither checked nor revertible.
    And `git status --porcelain` does not report gitignored files - those stay
    invisible to the check and are not restored by `git checkout .` (the wrapper
    names them before the run and reports what changed after it).

The default is --mode accept-edits --sandbox with permissions enforced. This was
chosen by measurement on 2026-09-13, not from the docs:

  - under it agy created and read files in the workspace and exited 0, and a
    write to a path outside the workspace was refused;
  - with --dangerously-skip-permissions instead, the same prompt wrote to a
    directory outside --dir that was not a git repository at all - nothing could
    revert it. That is what --allow-shell buys, and why it is opt-in;
  - agy's own command() grants are ignored in headless mode in both the plain
    and the regex: form, so shell work has no safer path than --allow-shell;
  - deny rules in agy's settings ARE honoured and outrank allow, which is the
    only working way to keep it away from a file. read_file(*) is the only read
    grant form that matches at all - path-scoped, prefix and regex: forms do
    not - so reads are broad by necessity and fenced by deny.

A tool call matching no rule is auto-denied and the run comes back empty
(antigravity-cli#548), with the wanted permission named on stderr. This wrapper
passes that line through, reads the permission name out of it, and turns the
empty answer into a non-zero exit that says what to change.

--no-tools is not a read-only switch: agy's permissions.allow still applies. The
clean-tree guard runs when the wrapper grants writes (--allow-shell, or
accept-edits mode), covers --add-dir as well as --dir, and --force skips it.
--no-tools without --mode skips the guard too, even though agy's
permissions.allow may still let it write.
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
# redirection. agy's answers can contain any Unicode character, so a write
# here is one non-cp1251 character away from crashing or corrupting output.
# Match the utf-8/errors="replace" already used for subprocess output below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_MODEL = "gemini-3.8-flash-high"

# agy's denial notice reads:
#   jetski: no output produced - a tool required the "command" permission that
#   headless mode cannot prompt for, so it was auto-denied. ...
# The dash between "produced" and "a tool" is a non-ASCII character that the
# console mangles, so match only the stable part around the quoted name.
DENIED_RE = re.compile(r'required the "([A-Za-z_][A-Za-z0-9_]*)" permission')

# What each denial actually means here, established by testing on 2026-09-13.
DENIAL_ADVICE = {
    "command": "agy tried a terminal command, which headless mode denies. If a "
               "file tool would do, re-brief with 'use your file-writing tool, not a "
               "terminal command'. Re-run with --allow-shell only if the task "
               "genuinely needs a shell (command() grants are ignored in headless mode).",
    "write_file": "The target is outside the workspace. Have agy write inside --dir "
                  "(the side directory); add another directory with --add-dir only if "
                  "it is a clean git repo prepared for this call, never the project's "
                  "working tree.",
    "read_file": "A read grant is missing, or a deny rule blocked the path. Only "
                 "read_file(*) matches in permissions.allow; deny outranks it.",
    "escalate_admin": "A terminal command tried to leave the sandbox. Re-run with "
                      "--allow-shell, or with --no-sandbox if the command is safe.",
}


def denied_permission(stderr_text):
    """Name of the permission agy was denied, or None if the notice is absent."""
    if not stderr_text:
        return None
    found = DENIED_RE.search(stderr_text)
    return found.group(1) if found else None

# CreateProcess caps the whole command line at 32767 chars. The real thing is
# what gets measured: subprocess.list2cmdline applies the same Windows argv
# quoting the OS will see, and quoting expands embedded quotes and backslashes,
# so a quote-heavy brief's command line is longer than the prompt string alone.
# The margin leaves room for anything appended between here and CreateProcess.
MAX_CMDLINE = 32767 - 512

# agy's stderr is copied through to the caller's transcript. It carries whatever
# agy's own tools printed, so cap it: a transcript is copied, logged and shared,
# and an unbounded paste of tool output is the cheapest way for something
# sensitive to end up in one. The denial notice is parsed before truncation, so
# nothing the wrapper needs is lost.
MAX_STDERR_CHARS = 4000

# Directories a delegated call must never be pointed at, whatever the flags say.
# These hold credentials, agent configuration, or application state; no
# legitimate delegated task needs agy's working directory to be one of them, and
# the permission entry that lets this script run unprompted does not constrain
# --dir at all. Paths are relative to the user's home.
#
# AppData is deliberately NOT blanket-forbidden: AppData/Local/Temp is where
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


def find_agy():
    env = os.environ.get("AGY_BIN")
    if env:
        if os.path.isfile(env):
            return env
        # A pinned build is pinned for a reason, usually a known bug in the
        # installed one; falling through would silently run a different build
        # and hide exactly the thing the pin was for.
        sys.exit(
            "agy-run: AGY_BIN={} is not a file. Fix or unset it; "
            "refusing to fall back to another build.".format(env)
        )
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        guess = os.path.join(local, "agy", "bin", "agy.exe")
        if os.path.isfile(guess):
            return guess
    found = shutil.which("agy") or shutil.which("agy.exe")
    if found:
        return found
    sys.exit("agy-run: cannot find agy.exe (set AGY_BIN to its full path)")


def git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )


def forbidden_subpath(real):
    """The FORBIDDEN_SUBPATHS entry `real` sits inside (or equals), or None."""
    home = os.path.abspath(os.path.expanduser("~"))
    # realpath maps neither a UNC administrative share (\\localhost\C$\...)
    # nor a subst-mapped drive onto the drive-letter form, so a forbidden
    # directory spelled that way walks past the comparison below. Refuse any
    # UNC path outright rather than try to canonicalise it.
    if os.path.normcase(real).startswith("\\\\"):
        sys.exit(
            "agy-run: refused, {} is a UNC path; use the drive-letter form.".format(real)
        )
    home_drive = os.path.splitdrive(home)[0]
    for rel in FORBIDDEN_SUBPATHS:
        forbidden = os.path.realpath(os.path.join(home, *rel.split("/")))
        inside = real == forbidden or real.startswith(forbidden + os.sep)
        if not inside and os.path.splitdrive(real)[0] != home_drive:
            # A subst drive gives the same directory a different drive
            # letter, which the string comparison misses. samefile sees
            # through it; it raises when either path does not exist - a
            # refused directory can be gone - so swallow that and keep
            # looking.
            try:
                inside = os.path.samefile(real, forbidden)
            except OSError:
                pass
        if inside:
            return rel
    return None


def check_prompt_file_allowed(path):
    """Refuse a --prompt-file that sits under the forbidden directories.

    The file's contents become the brief and ride through the whole call, so
    pointing this at a credential store reads it into the transcript. Same
    floor as --dir, and also not skippable with --force.
    """
    rel = forbidden_subpath(os.path.realpath(os.path.abspath(path)))
    if rel:
        sys.exit(
            "agy-run: refused, --prompt-file is inside {}, which holds credentials "
            "or agent configuration.\n         If you truly meant it, move the file "
            "out first.".format(rel)
        )


def check_dir_allowed(work_dir):
    """Refuse a working directory that no delegated task should ever have.

    The permission entry that lets this script run unprompted matches the
    program path only, not its arguments, so --dir is unconstrained by the
    thing that decided not to ask the human. This is the floor under that.

    Not skippable with --force: --force exists to get past a dirty tree, which
    is a judgement call, whereas pointing agy at a credential store is not.
    """
    home = os.path.abspath(os.path.expanduser("~"))
    real = os.path.realpath(work_dir)

    if real == home:
        sys.exit(
            "agy-run: refused, --dir is the home directory itself. Point it at a "
            "project, not at everything you own."
        )

    # Neither C:\ nor C:\Users is a git repository, so the clean-tree guard
    # normally refuses them for a different reason - but --force and
    # --no-tools skip that guard, and this one is the floor no flag lifts.
    # A drive root or any ancestor of home hands the worker every forbidden
    # directory at once.
    parents = []
    parent = os.path.dirname(home)
    while parent and parent != os.path.dirname(parent):
        parents.append(parent)
        parent = os.path.dirname(parent)
    if os.path.splitdrive(real)[1] in ("", os.sep) or real in parents:
        sys.exit(
            "agy-run: refused, --dir is a drive root or a parent of the home "
            "directory. Point it at a project, not at everything on the machine."
        )

    rel = forbidden_subpath(real)
    if rel:
        sys.exit(
            "agy-run: refused, --dir is inside {}, which holds credentials or "
            "agent configuration.\n         No delegated task needs to work "
            "there. Point --dir at a project directory instead.".format(rel)
        )

    # Optional per-machine narrowing, off unless the caller sets it. Semicolon
    # separated, since Windows paths contain colons.
    roots = os.environ.get("AGY_ALLOWED_ROOTS", "").strip()
    if roots:
        allowed = [os.path.realpath(r.strip()) for r in roots.split(";") if r.strip()]
        if not any(real == a or real.startswith(a + os.sep) for a in allowed):
            sys.exit(
                "agy-run: refused, --dir is outside AGY_ALLOWED_ROOTS.\n"
                "         dir:   {}\n         roots: {}".format(real, "; ".join(allowed))
            )


def warn_about_ignored(work_dir):
    """Name the gitignored files in --dir, which the clean-tree check cannot see.

    `git status --porcelain` omits ignored paths, so they are invisible before
    the run and unrestored by `git checkout .` after it. Backing them up would
    be out of proportion here; saying which files are exposed is not.
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
        "agy-run: note: {} gitignored path(s) in --dir are outside the safety net "
        "- agy can change them and `git checkout .` will not bring them back: "
        "{}{}\n".format(len(ignored), shown, more)
    )


def check_clean_tree(work_dir):
    """Edits are auto-approved, so require a clean git tree first.

    A clean tree turns any result agy produces into `git checkout .`; without one
    there is nothing to undo a bad edit with. Note that `git status --porcelain`
    does not report gitignored files, so those stay invisible to this check and
    are not restored by `git checkout .` - warn_about_ignored names them.
    """
    probe = git(["rev-parse", "--is-inside-work-tree"], work_dir)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        sys.exit(
            "agy-run: refused, {} is not a git repository. agy runs with edits\n"
            "         auto-approved and can edit files there with nothing to revert.\n"
            "         Run the call in a git repository with a clean tree, or pass\n"
            "         --no-tools if the task needs no files. --force skips this check and\n"
            "         is for an explicit request from the human only.".format(work_dir)
        )
    status = git(["status", "--porcelain"], work_dir)
    if status.returncode != 0:
        sys.exit("agy-run: refused, `git status` failed:\n" + status.stderr)
    if status.stdout.strip():
        dirty = status.stdout.strip().splitlines()
        preview = "\n".join("         " + line for line in dirty[:10])
        more = "" if len(dirty) <= 10 else "\n         ... and {} more".format(len(dirty) - 10)
        sys.exit(
            "agy-run: refused, working tree is dirty - commit or stash first so "
            "the delegated edits can be reverted (gitignored files are not shown "
            "here and are not reverted either):\n" + preview + more
        )


def report_changes(dirs):
    """Say what agy actually touched.

    The clean-tree check was a point-in-time guarantee; this does not close
    the window between the check and agy's first write, but it does mean
    nobody has to go looking for what changed.
    """
    for d in dirs:
        after = git(["status", "--porcelain"], d)
        if after.returncode != 0:
            first_line = (after.stderr or "").splitlines()[0] if after.stderr else ""
            sys.stderr.write(
                "agy-run: warning: change report unavailable for {} (git status "
                "failed: {})\n".format(d, first_line)
            )
            continue
        touched = [l for l in after.stdout.splitlines() if l.strip()]
        if not touched:
            continue
        shown = "\n".join("         " + t for t in touched[:15])
        more = "" if len(touched) <= 15 else "\n         ... and {} more".format(
            len(touched) - 15
        )
        sys.stderr.write(
            "agy-run: {} path(s) changed in {} - revert with `git checkout .` there "
            "if this is not what you wanted:\n{}{}\n".format(len(touched), d, shown, more)
        )


def build_cmd(exe, prompt, args, mode, sandbox, blanket):
    cmd = [
        exe,
        "-p=" + prompt,
        "--model", args.model,
        "--output-format", "json",
        "--print-timeout", "{}m".format(args.timeout_min),
    ]
    if args.effort:
        cmd += ["--effort", args.effort]
    if args.agent:
        cmd += ["--agent", args.agent]
    if sandbox:
        cmd.append("--sandbox")
    if mode:
        cmd += ["--mode", mode]
    if args.add_dir:
        for d in args.add_dir:
            cmd += ["--add-dir", d]
    if blanket:
        cmd.append("--dangerously-skip-permissions")
    return cmd


def kill_tree(proc):
    """taskkill takes the whole tree, which proc.kill() cannot.

    Every way taskkill can fail is invisible, so always fall back to killing
    the child ourselves: an orphaned agy keeps writing in --dir with no
    reader on its pipe, and nothing in the output would say so.
    """
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10
        )
    except Exception as exc:
        sys.stderr.write("agy-run: taskkill failed ({}), killing the child only\n".format(exc))
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def echo_stderr(err):
    """Copy agy's stderr through, truncated in the middle.

    Truncated, not scrubbed: this is agy's own tool output and it lands in a
    transcript. Keep both ends - the denial notice tends to lead, the
    traceback to trail - and say how much was dropped. denied_permission()
    reads the full text, not this copy, so nothing the wrapper needs is lost.
    """
    if not err:
        return
    if len(err) <= MAX_STDERR_CHARS:
        sys.stderr.write(err)
        return
    half = MAX_STDERR_CHARS // 2
    sys.stderr.write(
        err[:half]
        + "\n... agy-run: {} chars of agy stderr omitted ...\n".format(
            len(err) - MAX_STDERR_CHARS
        )
        + err[-half:]
    )


def parse_payload(raw):
    """The last complete JSON object in agy's stdout, or None.

    agy is on a weekly release cadence and may print banners or progress
    lines around the payload, so anchoring on the first brace anywhere would
    start the parse mid-diagnostic. Try the whole stdout first, then each
    line that begins with `{` once leading whitespace is skipped, from the
    last such line to the first, and accept only an object that runs to the
    end of the stream - which is where agy flushes its result. Leading noise
    is tolerated only if the payload starts on its own line; trailing text
    after the object makes the parse fail by design, so a truncated or mixed
    stream is not mistaken for a payload. The scan is linear in the number
    of lines, not in the number of braces.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    # Decode at the `{` itself rather than at the line start, so an indented
    # payload line (`   {"a": 1}`) still parses.
    starts = []
    offset = 0
    for line in raw.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("{"):
            starts.append(offset + (len(line) - len(stripped)))
        offset += len(line)
    for start in reversed(starts):
        try:
            obj, end = decoder.raw_decode(raw, start)
        except ValueError:
            continue
        if isinstance(obj, dict) and not raw[end:].strip():
            return obj
    return None


def main():
    ap = argparse.ArgumentParser(
        prog="agy-run",
        description="Run one self-contained task through the Antigravity CLI.",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt", help="the brief, inline")
    src.add_argument("--prompt-file", help="file holding the brief (preferred for long ones)")
    ap.add_argument("--dir", default=".", help="working directory for agy (default: cwd)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="default: " + DEFAULT_MODEL)
    ap.add_argument("--effort", choices=["low", "medium", "high"])
    ap.add_argument("--agent", help="custom agy agent, e.g. 'Senior Developer'")
    ap.add_argument(
        "--allow-shell",
        action="store_true",
        help="let agy run terminal commands, by passing --dangerously-skip-permissions. "
        "Needed for any shell work: agy's own command() grants are ignored in headless "
        "mode, in both the plain and the regex: form. It also removes every other "
        "boundary - measured: agy then writes outside --dir with nothing to revert it - "
        "so the clean-tree guard is all that is left. Use only when the task needs a "
        "shell.",
    )
    ap.add_argument(
        "--no-tools",
        action="store_true",
        help="pure-reasoning prompt: no sandbox, no accept-edits, no skip-permissions. "
        "agy's own permissions.allow still applies, so this is not a read-only switch. "
        "Also skips the clean-tree check and the change report, although agy may still "
        "write.",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="skip the clean-tree check. Does not skip the forbidden-directory check. "
        "The guard's scope: it covers git-tracked files inside --dir and --add-dir "
        "only - gitignored files and everything outside those directories are "
        "neither checked nor revertible. It also suppresses the gitignored-paths note "
        "and the after-run change report, so check `git status` yourself.",
    )
    ap.add_argument("--timeout-min", type=int, default=5, help="default: 5")
    ap.add_argument(
        "--no-sandbox", action="store_true",
        help="do not pass --sandbox (it is on by default)",
    )
    ap.add_argument(
        "--mode", choices=["accept-edits", "plan"],
        help="agy execution mode; defaults to accept-edits unless --allow-shell "
        "or --no-tools is given",
    )
    ap.add_argument(
        "--add-dir", action="append",
        help="give agy an additional workspace directory; repeatable. Each one must "
        "be a clean git repository, same as --dir",
    )
    args = ap.parse_args()

    if args.timeout_min <= 0:
        ap.error("--timeout-min must be positive, got {}".format(args.timeout_min))

    work_dir = os.path.abspath(args.dir)
    if not os.path.isdir(work_dir):
        sys.exit("agy-run: no such directory: " + work_dir)

    if args.prompt_file:
        if not os.path.isfile(args.prompt_file):
            sys.exit("agy-run: no such prompt file: " + args.prompt_file)
        check_prompt_file_allowed(args.prompt_file)
        with open(args.prompt_file, encoding="utf-8") as fh:
            prompt = fh.read()
    else:
        prompt = args.prompt
    prompt = prompt.strip()
    if not prompt:
        sys.exit("agy-run: the prompt is empty")

    # Default is the configuration measured on 2026-09-13: edits auto-approved,
    # shell commands still gated, sandbox on. Under it agy could not write
    # outside the workspace; with --allow-shell it could, and did.
    if args.no_tools:
        blanket, mode, sandbox = False, args.mode, False
    elif args.allow_shell:
        # The one combination measured on 2026-09-13; --sandbox is left off so
        # this flag means one tested configuration rather than an untested one.
        blanket, mode, sandbox = True, args.mode, False
    else:
        blanket, mode, sandbox = False, args.mode or "accept-edits", not args.no_sandbox

    # Unconditional, and before anything else: --force is about a dirty tree,
    # not about where agy is allowed to work.
    extra_dirs = [os.path.abspath(e) for e in args.add_dir or []]
    for d in [work_dir] + extra_dirs:
        check_dir_allowed(d)

    # Gate the guard on what agy could actually do, not on any single flag.
    can_write = blanket or mode == "accept-edits"
    if can_write and not args.force:
        check_clean_tree(work_dir)
        # --add-dir hands agy a second writable directory the check above never
        # looked at. Hold each one to the same standard.
        for extra in extra_dirs:
            check_clean_tree(extra)
        for d in [work_dir] + extra_dirs:
            warn_about_ignored(d)

    exe = find_agy()
    cmd = build_cmd(exe, prompt, args, mode, sandbox, blanket)
    quoted = len(subprocess.list2cmdline(cmd))
    # Set when the brief is handed over by path instead of inline; the
    # CANNOT READ BRIEF check below needs the path it pointed at.
    brief_ref = None
    if quoted > MAX_CMDLINE:
        if not args.prompt_file:
            # An inline brief is never auto-converted: converting it would
            # need a file to point at, and inventing one is a silent rewrite
            # of what the caller passed. Say what to do and fail.
            sys.exit(
                "agy-run: the quoted command line is {} chars, over the "
                "wrapper's {} char ceiling (CreateProcess caps at 32767). The "
                "brief alone is {} chars - Windows argv quoting expands "
                "embedded quotes and backslashes, so quote-heavy briefs "
                "overflow well before their raw length does. Pass it as "
                "--prompt-file.".format(
                    quoted, MAX_CMDLINE, len(prompt)
                )
            )
        # Too long for one argv element: point agy at the file instead. This
        # costs a read tool call inside agy, which is the degraded path - keep
        # briefs short.
        ref = os.path.abspath(args.prompt_file)
        ref_real = os.path.normcase(os.path.realpath(ref))
        workspace_dirs = [
            os.path.normcase(os.path.realpath(d)) for d in [work_dir] + extra_dirs
        ]
        if not any(
            ref_real == d or ref_real.startswith(d + os.sep) for d in workspace_dirs
        ):
            sys.stderr.write(
                "agy-run: warning: the brief file {} is outside the workspace. Reads "
                "outside it have worked in measurement (see the agy skill), but keep "
                "the brief under --dir or pass --add-dir so the call does not depend "
                "on that.\n".format(ref)
            )
        brief_ref = ref
        prompt = (
            "Read the file {} with your file-reading tool; the path is absolute, so no "
            "directory listing, search or terminal command is needed to find it. "
            "Then follow the instructions in it. "
            "If you cannot read it, reply with exactly: CANNOT READ BRIEF and nothing else."
        ).format(ref)
        cmd = build_cmd(exe, prompt, args, mode, sandbox, blanket)
        sys.stderr.write(
            "agy-run: brief would overflow the {}-char Windows command line, "
            "passing it by path instead of inline\n".format(MAX_CMDLINE)
        )

    # Hard wall clock on top of agy's own timeout: #548 can hang a tool call past
    # --print-timeout, and a wedged subprocess blocks the calling session.
    hard_limit = args.timeout_min * 60 + 30
    proc = subprocess.Popen(
        cmd,
        cwd=work_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        out, err = proc.communicate(timeout=hard_limit)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        if can_write and not args.force:
            report_changes([work_dir] + extra_dirs)
        sys.exit(
            "agy-run: agy did not return within {}s. Known issue: a tool call can "
            "hang in headless mode (antigravity-cli#548). Do not retry the same "
            "call unchanged: if the task is large, raise --timeout-min deliberately; "
            "otherwise narrow the brief or report the hang.".format(hard_limit)
        )

    echo_stderr(err)

    raw = (out or "").strip()
    payload = parse_payload(raw)
    if payload is None:
        sys.exit(
            "agy-run: agy returned no parseable JSON object (exit {}).\n{}".format(
                proc.returncode, raw[:2000]
            )
        )

    # `null`, a list or a bare number all parse as valid JSON, and every field
    # read below would raise on them. Fail with the diagnostic instead.
    if not isinstance(payload, dict):
        sys.exit(
            "agy-run: agy returned JSON that is not an object (exit {}).\n{}".format(
                proc.returncode, raw[:2000]
            )
        )

    # The clean-tree check was a point-in-time guarantee, so say what the tree
    # looks like now. This does not close the window between the check and agy's
    # first write, but it does mean nobody has to go looking for what changed.
    if can_write and not args.force:
        report_changes([work_dir] + extra_dirs)

    status = payload.get("status", "UNKNOWN")
    usage = payload.get("usage", {})
    print(
        "agy-run: status={} model={} in={} out={} cache_read={} total={} {:.0f}s conv={}".format(
            status,
            args.model,
            usage.get("input_tokens", "?"),
            usage.get("output_tokens", "?"),
            usage.get("cache_read_tokens", "?"),
            usage.get("total_tokens", "?"),
            payload.get("duration_seconds", 0),
            payload.get("conversation_id", "?"),
        ),
        file=sys.stderr,
    )

    if status != "SUCCESS":
        sys.stderr.write("agy-run: " + str(payload.get("error", "no error text")) + "\n")
        return 1

    response = payload.get("response", "")
    if "\ufffd" in response:
        sys.stderr.write(
            "agy-run: warning: output contained invalid UTF-8; some characters "
            "were replaced\n"
        )

    if brief_ref is not None and response.strip() == "CANNOT READ BRIEF":
        # The brief went by path and agy could not open it; nothing after that
        # is an answer to it.
        sys.stderr.write(
            "agy-run: agy could not read the brief at {}\n".format(brief_ref)
        )
        return 1

    if proc.returncode != 0:
        # A payload can be complete and its answer still truncated if agy died
        # after flushing stdout. This contract is "exit 0 only on success", so a
        # dead child is a failure even when the envelope says otherwise. The
        # answer is printed first, so nothing is lost by failing here.
        sys.stdout.write(response)
        sys.stderr.write(
            "agy-run: agy exited {} despite reporting SUCCESS. The answer above may "
            "be truncated; treat this run as failed.\n".format(proc.returncode)
        )
        return 1
    if not response.strip():
        # agy reports SUCCESS with an empty response when a tool call was
        # auto-denied, and names the permission it wanted on stderr. Read it
        # rather than guessing: the fix differs per permission.
        wanted = denied_permission(err)
        if blanket:
            hint = (
                "Tools were fully auto-approved, so this is not a permission problem "
                "- narrow the task, or check the line above."
            )
        elif wanted:
            hint = "It was denied \"{}\". {}".format(wanted, DENIAL_ADVICE.get(
                wanted,
                "The permission is not in agy's allow list. Report its name to the "
                "human: that list lives in agy's own settings, which the agent does "
                "not edit. Re-run with --allow-shell only if the task genuinely needs "
                "a shell.",
            ))
        else:
            hint = (
                "No permission name was found in agy's output, so the cause is not "
                "the usual auto-denial - read the line above before retrying."
            )
        sys.stderr.write(
            "agy-run: agy returned SUCCESS with an empty answer - a tool call was "
            "auto-denied. " + hint + " Do not retry the same call unchanged.\n"
        )
        return 1

    sys.stdout.write(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())
