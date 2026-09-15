#!/usr/bin/env python3
"""Delegate a self-contained task to the Antigravity CLI (agy) in headless mode.

Claude Code stays the orchestrator on the Anthropic subscription; this hands one
brief to agy, which runs on the Google AI Pro quota, and returns its answer plus
the price of the call.

Why a wrapper instead of calling `agy -p` directly:
  - pins --output-format json and --print-timeout, so a hung call fails fast
    instead of eating the default 5 minutes silently;
  - passes the prompt as a single argv element, so quotes and newlines survive
    (Windows PowerShell 5.1 mangles them when calling a native exe);
  - reports usage, so the caller can see a call cost ~17k tokens read / ~44k
    write and stop before burning the quota blind;
  - exits non-zero when agy reports failure OR returns an empty answer, which is
    what an auto-denied tool call looks like: status SUCCESS, response "";
  - refuses to run on a dirty or non-git tree, which is the only thing standing
    between --dangerously-skip-permissions and unrecoverable edits (--force skips
    this check while leaving tools on). The guarantee is scoped to --dir: nothing
    confines agy's file tools to that directory, so edits outside it are neither
    checked nor revertible. It is also scoped to what `git status --porcelain`
    reports, which does not include gitignored files - those stay invisible to
    the check and are not restored by `git checkout .`.

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
clean-tree guard runs whenever agy could write, covers --add-dir as well as
--dir, and --force skips it.
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
    "command": "The task needs a shell, and agy's command() grants are ignored in "
               "headless mode - re-run with --allow-shell.",
    "write_file": "The target is outside the workspace. Pass its directory as "
                  "--add-dir (it must be a clean git repo too), or point --dir at it.",
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

# CreateProcess caps the whole command line at 32767 chars; leave room for the
# other flags, the exe path, and Windows argv quoting, which expands embedded
# quotes and backslashes so a quote-heavy brief's quoted command line can be
# longer than the raw prompt string.
MAX_INLINE_PROMPT = 24000

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
    if env and os.path.isfile(env):
        return env
    if env:
        sys.stderr.write("agy-run: warning: AGY_BIN={} is not a file, ignoring it\n".format(env))
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

    for rel in FORBIDDEN_SUBPATHS:
        forbidden = os.path.realpath(os.path.join(home, *rel.split("/")))
        if real == forbidden or real.startswith(forbidden + os.sep):
            sys.exit(
                "agy-run: refused, --dir is inside {}, which holds credentials or "
                "agent configuration.\n         No delegated task needs to work "
                "there. If you truly meant it, move the files out first.".format(rel)
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
    """Tools auto-approve every call, so require a clean git tree first.

    A clean tree turns any result agy produces into `git checkout .`; without one
    there is nothing to undo a bad edit with. Note that `git status --porcelain`
    does not report gitignored files, so those stay invisible to this check and
    are not restored by `git checkout .` - warn_about_ignored names them.
    """
    probe = git(["rev-parse", "--is-inside-work-tree"], work_dir)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        sys.exit(
            "agy-run: refused, {} is not a git repository. agy runs with tools\n"
            "         auto-approved and can edit files there with nothing to revert.\n"
            "         Run `git init`, or pass --no-tools, or --force.".format(work_dir)
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
        "agy's own permissions.allow still applies, so this is not a read-only switch.",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="skip the clean-tree check. Does not skip the forbidden-directory check",
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
        sys.exit("agy-run: --timeout-min must be positive, got {}".format(args.timeout_min))

    work_dir = os.path.abspath(args.dir)
    if not os.path.isdir(work_dir):
        sys.exit("agy-run: no such directory: " + work_dir)

    if args.prompt_file:
        if not os.path.isfile(args.prompt_file):
            sys.exit("agy-run: no such prompt file: " + args.prompt_file)
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
        # Exactly the old behaviour, and nothing more: --sandbox is left off so
        # this flag means one known thing rather than an untested combination.
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

    # Too long for one argv element: point agy at the file instead. This costs a
    # read tool call inside agy, which is the degraded path - keep briefs short.
    if len(prompt) > MAX_INLINE_PROMPT:
        if not args.prompt_file:
            sys.exit(
                "agy-run: prompt is {} chars, over the {} limit; pass it as "
                "--prompt-file so it can be referenced by path. Quote-heavy briefs "
                "should use --prompt-file well before the limit.".format(
                    len(prompt), MAX_INLINE_PROMPT
                )
            )
        ref = os.path.abspath(args.prompt_file)
        prompt = "Read the file {} and follow the instructions in it.".format(ref)
        print(
            "agy-run: brief exceeds {} chars, passing it by path instead of "
            "inline".format(MAX_INLINE_PROMPT),
            file=sys.stderr,
        )

    cmd = [
        find_agy(),
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
        # taskkill takes the whole tree, which proc.kill() cannot. But every way
        # it can fail is invisible, so always fall back to killing the child
        # ourselves: an orphaned agy keeps writing in --dir with no reader on its
        # pipe, and nothing in the output would say so.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
            )
        except Exception as exc:
            sys.stderr.write("agy-run: taskkill failed ({}), killing the child only\n".format(exc))
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        sys.exit(
            "agy-run: agy did not return within {}s. Known issue: a tool call can "
            "hang in headless mode (antigravity-cli#548). Do not retry the same "
            "call; narrow it to read-only, or do it yourself.".format(hard_limit)
        )

    if err:
        # Truncated, not scrubbed: this is agy's tool output and it lands in a
        # transcript. Keep both ends - the denial notice tends to lead, the
        # traceback to trail - and say how much was dropped.
        if len(err) > MAX_STDERR_CHARS:
            half = MAX_STDERR_CHARS // 2
            sys.stderr.write(
                err[:half]
                + "\n... agy-run: {} chars of agy stderr omitted ...\n".format(
                    len(err) - MAX_STDERR_CHARS
                )
                + err[-half:]
            )
        else:
            sys.stderr.write(err)

    raw = out.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        if start == -1:
            sys.exit(
                "agy-run: agy returned no JSON (exit {}).\n{}".format(proc.returncode, raw[:2000])
            )
        try:
            payload = json.loads(raw[start:])
        except json.JSONDecodeError as exc:
            sys.exit("agy-run: cannot parse agy output ({}):\n{}".format(exc, raw[:2000]))

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
        for d in [work_dir] + extra_dirs:
            after = git(["status", "--porcelain"], d)
            touched = [l for l in after.stdout.splitlines() if l.strip()]
            if touched:
                shown = "\n".join("         " + t for t in touched[:15])
                more = "" if len(touched) <= 15 else "\n         ... and {} more".format(
                    len(touched) - 15
                )
                sys.stderr.write(
                    "agy-run: {} path(s) changed in {} - revert with `git checkout .` "
                    "there if this is not what you wanted:\n{}{}\n".format(
                        len(touched), d, shown, more
                    )
                )

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
                "Add an allow-rule for it in ~/.gemini/antigravity-cli/settings.json, "
                "or re-run with --allow-shell.",
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
