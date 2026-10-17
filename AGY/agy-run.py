#!/usr/bin/env python3
"""Run one self-contained task through the Antigravity CLI (agy) in headless mode.

The brief goes to agy as one argv element (`-p=`), the answer comes out on stdout, token usage
on stderr. The default is `--mode accept-edits --sandbox` with permissions enforced, behind a
pre-call snapshot that makes any change revertible. Measurements and the guard's limits: skills/agy/SKILL.md, AGY/README.md.

    python agy-run.py --dir <any project dir> --prompt "<brief>"    (or --prompt-file <path>)

Exit codes: 0 success, 1 agy failed or reported an error, 2 refused before any call,
3 timeout.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import workers_common as common  # noqa: E402

PROG = "agy-run"
common.utf8_stdio()

DEFAULT_MODEL = "gemini-3.8-flash-high"

EXIT_CODES = (
    "exit codes: 0 success; 1 agy failed or reported an error; 2 refused before any call "
    "(bad arguments, forbidden directory, bad prompt file, missing binary, "
    "command line too long); 3 timeout"
)

# agy's denial notice reads:
#   jetski: no output produced - a tool required the "command" permission that
#   headless mode cannot prompt for, so it was auto-denied. ...
# The dash is a non-ASCII character the console mangles, so match only the stable part.
DENIED_RE = re.compile(r'required the "([A-Za-z_][A-Za-z0-9_]*)" permission')

DENIAL_ADVICE = {
    "command": "agy tried a terminal command, which headless mode denies. If a "
               "file tool would do, re-brief with 'use your file-writing tool, not a "
               "terminal command'. Re-run with --allow-shell only if the task "
               "genuinely needs a shell (command() grants are ignored in headless mode).",
    "write_file": "The target is outside the workspace. Have agy write inside --dir, "
                  "or pass the target's directory with --add-dir.",
    "read_file": "A read grant is missing, or a deny rule blocked the path. Only "
                 "read_file(*) matches in permissions.allow; deny outranks it.",
    "read_url": "Web access was denied: read_url(*) is missing from agy's permissions.allow. "
                "The wrapper adds it before every call; a warning above says why it could "
                "not.",
    "escalate_admin": "A terminal command tried to leave the sandbox. Re-run with "
                      "--allow-shell, or with --no-sandbox if the command is safe.",
}

# CreateProcess caps the whole command line at 32767 chars; subprocess.list2cmdline applies
# the same quoting the OS will see. The margin leaves room for anything appended later.
MAX_CMDLINE = 32767 - 512


def denied_permission(stderr_text):
    """Name of the permission agy was denied, or None if the notice is absent."""
    if not stderr_text:
        return None
    found = DENIED_RE.search(stderr_text)
    return found.group(1) if found else None


SETTINGS_FILE = os.path.join(
    os.path.expanduser("~"), ".gemini", "antigravity-cli", "settings.json")

# Read-only web tools, granted in agy's own settings: headless mode cannot prompt, so without
# them a request that needs the web (research, "current as of today") is auto-denied, and the
# only other way in is --allow-shell, which lifts every boundary.
WEB_GRANTS = ["read_url(*)"]


def ensure_web_grants(path=SETTINGS_FILE):
    """Add WEB_GRANTS to agy's permissions.allow before every call; agy rewrites the file itself.

    Only these entries are added; nothing else in the file is read or changed. A missing or
    unparseable file is left alone with a warning: agy then denies web access as before.
    """
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        allow = data.setdefault("permissions", {}).setdefault("allow", [])
        missing = [g for g in WEB_GRANTS if g not in allow]
        if not missing:
            return
        allow.extend(missing)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except (OSError, ValueError, AttributeError) as exc:
        sys.stderr.write(
            "agy-run: warning: could not grant web access in {} ({}); a request that "
            "needs the web will be denied.\n".format(path, exc))


def find_agy():
    env = os.environ.get("AGY_BIN")
    if env:
        if os.path.isfile(env):
            return env
        # A pinned build is pinned for a reason; falling through would hide it.
        common.refuse(
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
    common.refuse("agy-run: cannot find agy.exe (set AGY_BIN to its full path)")


@dataclass(frozen=True)
class Policy:
    blanket: bool          # --dangerously-skip-permissions
    mode: Optional[str]    # agy --mode, None when not passed
    sandbox: bool          # --sandbox
    can_write: bool        # agy can change files
    guarded: bool          # snapshot before, change report after


def decide_policy(args):
    """What the flags grant agy. Raises ValueError on a contradiction.

    --no-tools is a read-only reasoning call: --mode plan with the sandbox on, no
    accept-edits and no skip-permissions; nothing is written, so the snapshot is skipped.
    """
    if args.no_tools:
        if args.allow_shell:
            raise ValueError("--no-tools and --allow-shell contradict each other")
        if args.mode not in (None, "plan"):
            raise ValueError("--no-tools is read-only (--mode plan); drop --mode " + args.mode)
        if args.no_sandbox:
            raise ValueError("--no-tools keeps the sandbox on; drop --no-sandbox")
        blanket, mode, sandbox = False, "plan", True
    elif args.allow_shell:
        # The one measured shell configuration: skip-permissions without --sandbox.
        blanket, mode, sandbox = True, args.mode, False
    else:
        blanket, mode, sandbox = False, args.mode or "accept-edits", not args.no_sandbox
    can_write = blanket or mode == "accept-edits"
    return Policy(blanket, mode, sandbox, can_write, can_write and not args.force)


def build_cmd(exe, prompt, args, mode, sandbox, blanket, extra_dirs):
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
    for d in extra_dirs:
        cmd += ["--add-dir", d]
    if blanket:
        cmd.append("--dangerously-skip-permissions")
    return cmd


def fit_command(exe, prompt, args, policy, work_dir, extra_dirs):
    """The command, and the brief file's path when the brief goes by path instead of inline.

    An inline brief over the ceiling is refused, never converted: that would need a file the
    caller did not pass. A --prompt-file brief over it is handed to agy by path.
    """
    cmd = build_cmd(exe, prompt, args, policy.mode, policy.sandbox, policy.blanket, extra_dirs)
    quoted = len(subprocess.list2cmdline(cmd))
    if quoted <= MAX_CMDLINE:
        return cmd, None
    if not args.prompt_file:
        common.refuse(
            "agy-run: the quoted command line is {} chars, over the "
            "wrapper's {} char ceiling (CreateProcess caps at 32767). The "
            "brief alone is {} chars - Windows argv quoting expands "
            "embedded quotes and backslashes, so quote-heavy briefs "
            "overflow well before their raw length does. Pass it as "
            "--prompt-file.".format(quoted, MAX_CMDLINE, len(prompt))
        )
    ref = os.path.abspath(args.prompt_file)
    ref_real = os.path.normcase(os.path.realpath(ref))
    workspace_dirs = [os.path.normcase(os.path.realpath(d)) for d in [work_dir] + extra_dirs]
    if not any(ref_real == d or ref_real.startswith(d + os.sep) for d in workspace_dirs):
        sys.stderr.write(
            "agy-run: warning: the brief file {} is outside the workspace. Reads "
            "outside it have worked in measurement (see the agy skill), but keep "
            "the brief under --dir or pass --add-dir so the call does not depend "
            "on that.\n".format(ref)
        )
    by_path = (
        "Read the file {} with your file-reading tool; the path is absolute, so no "
        "directory listing, search or terminal command is needed to find it. "
        "Then follow the instructions in it. "
        "If you cannot read it, reply with exactly: CANNOT READ BRIEF and nothing else."
    ).format(ref)
    sys.stderr.write(
        "agy-run: brief would overflow the {}-char Windows command line, "
        "passing it by path instead of inline\n".format(MAX_CMDLINE)
    )
    cmd = build_cmd(exe, by_path, args, policy.mode, policy.sandbox, policy.blanket, extra_dirs)
    return cmd, ref


@dataclass(frozen=True)
class Outcome:
    code: int
    answer: str = ""    # written to stdout
    message: str = ""   # written to stderr last, when not empty


def classify_result(payload, raw, returncode, stderr_text, brief_ref, blanket):
    """Exit code, answer and closing message from agy's payload, stdout, exit code and stderr."""
    if payload is None:
        return Outcome(common.EXIT_FAILED, message=(
            "agy-run: agy returned no parseable JSON object (exit {}).\n{}".format(
                returncode, raw[:2000])))

    if payload.get("status", "UNKNOWN") != "SUCCESS":
        return Outcome(common.EXIT_FAILED, message=(
            "agy-run: " + str(payload.get("error") or "no error text")))

    response = common.as_text(payload.get("response"))

    if brief_ref is not None and response.strip() == "CANNOT READ BRIEF":
        return Outcome(common.EXIT_FAILED, message=(
            "agy-run: agy could not read the brief at {}".format(brief_ref)))

    if returncode != 0:
        # agy can die after flushing a complete-looking payload; exit 0 only on success.
        return Outcome(common.EXIT_FAILED, response, (
            "agy-run: agy exited {} despite reporting SUCCESS. The answer above may "
            "be truncated; treat this run as failed.".format(returncode)))

    if not response.strip():
        # SUCCESS with an empty response is what an auto-denied tool call looks like
        # (antigravity-cli#548); agy names the permission it wanted on stderr.
        wanted = denied_permission(stderr_text)
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
        return Outcome(common.EXIT_FAILED, message=(
            "agy-run: agy returned SUCCESS with an empty answer - a tool call was "
            "auto-denied. " + hint + " Do not retry the same call unchanged."))

    warning = ("agy-run: warning: output contained invalid UTF-8; some characters "
               "were replaced" if "�" in response else "")
    return Outcome(common.EXIT_OK, response, warning)


def report_cost(payload, requested_model):
    """One usage line; the model is the one agy reports, else the one requested."""
    usage = common.as_dict(payload.get("usage"))
    reported = payload.get("model")
    model = reported if isinstance(reported, str) and reported.strip() else requested_model
    sys.stderr.write(
        "agy-run: status={} model={} in={} out={} cache_read={} total={} {:.0f}s conv={}\n".format(
            payload.get("status", "UNKNOWN"),
            model,
            usage.get("input_tokens", "?"),
            usage.get("output_tokens", "?"),
            usage.get("cache_read_tokens", "?"),
            usage.get("total_tokens", "?"),
            common.as_number(payload.get("duration_seconds")),
            payload.get("conversation_id", "?"),
        )
    )


def run(cmd, work_dir, extra_dirs, policy, hard_limit, brief_ref, requested_model):
    dirs = [work_dir] + extra_dirs
    heads = {d: common.head_commit(d) for d in dirs} if policy.guarded else {}
    snaps = common.take_snapshots(dirs, PROG) if policy.guarded else {}
    # Hard wall clock on top of agy's own --print-timeout: a tool call can hang past it
    # (antigravity-cli#548). agy takes the brief from -p=, never from stdin.
    try:
        returncode, out, err = common.run_worker(
            cmd, work_dir, common.scrubbed_env(), hard_limit, PROG)
    except subprocess.TimeoutExpired:
        if policy.guarded:
            common.report_changes(snaps, heads, PROG)
        common.die(
            "agy-run: agy did not return within {}s. Known issue: a tool call can "
            "hang in headless mode (antigravity-cli#548). Do not retry the same "
            "call unchanged: if the task is large, raise --timeout-min deliberately; "
            "otherwise narrow the brief or report the hang.".format(hard_limit),
            common.EXIT_TIMEOUT,
        )

    common.echo_stderr(err, PROG)

    raw = (out or "").strip()
    payload = common.parse_payload(raw)
    outcome = classify_result(payload, raw, returncode, err, brief_ref, policy.blanket)

    if policy.guarded:
        common.report_changes(snaps, heads, PROG)
    if payload is not None:
        report_cost(payload, requested_model)

    sys.stdout.write(outcome.answer)
    if outcome.message:
        sys.stderr.write(outcome.message + "\n")
    return outcome.code


def main():
    ap = argparse.ArgumentParser(
        prog="agy-run",
        description="Run one self-contained task through the Antigravity CLI.",
        epilog=EXIT_CODES,
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt", help="the brief, inline")
    src.add_argument("--prompt-file", help="UTF-8 file holding the brief (preferred for long ones)")
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
        "so the pre-call snapshot is all that is left. Use only when the task needs a "
        "shell.",
    )
    ap.add_argument(
        "--no-tools",
        action="store_true",
        help="read-only reasoning call: --mode plan with the sandbox on, no accept-edits, "
        "no skip-permissions. Nothing is written, so the snapshot and the change "
        "report are skipped. Refused together with --allow-shell, --mode accept-edits or "
        "--no-sandbox.",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="skip the pre-call snapshot, so nothing can be reverted and no change "
        "report is printed. Does not skip the forbidden-directory check. Even with the "
        "snapshot, gitignored files and everything outside --dir and --add-dir are "
        "not revertible.",
    )
    ap.add_argument("--timeout-min", type=int, default=5, help="default: 5")
    ap.add_argument(
        "--no-sandbox", action="store_true",
        help="do not pass --sandbox (it is on by default)",
    )
    ap.add_argument(
        "--mode", choices=["accept-edits", "plan"],
        help="agy execution mode; defaults to accept-edits unless --allow-shell "
        "or --no-tools is given (--no-tools always runs plan)",
    )
    ap.add_argument(
        "--add-dir", action="append",
        help="give agy an additional workspace directory; repeatable. Each one must "
        "is snapshotted, same as --dir",
    )
    args = ap.parse_args()

    if args.timeout_min <= 0:
        ap.error("--timeout-min must be positive, got {}".format(args.timeout_min))

    work_dir = os.path.abspath(args.dir)
    if not os.path.isdir(work_dir):
        common.refuse("agy-run: no such directory: " + work_dir)

    prompt = common.read_prompt(args.prompt, args.prompt_file, PROG)

    try:
        policy = decide_policy(args)
    except ValueError as exc:
        common.refuse("agy-run: {}".format(exc))

    # Unconditional, and before anything else: --force is about the snapshot,
    # not about where agy is allowed to work.
    # agy runs with cwd=work_dir, so a relative --add-dir means work_dir/<it>; resolve once.
    extra_dirs = [os.path.realpath(os.path.join(work_dir, e)) for e in args.add_dir or []]
    for d in [work_dir] + extra_dirs:
        common.check_dir_allowed(d, PROG, "AGY_ALLOWED_ROOTS")

    exe = find_agy()
    # A .cmd/.bat shim runs through cmd.exe, which re-parses the brief in argv as shell syntax.
    if not exe.lower().endswith(".exe"):
        common.refuse(
            "agy-run: refused, {} is not an .exe. A .cmd or .bat shim would pass the "
            "brief through cmd.exe; set AGY_BIN to the full path of agy.exe.".format(exe)
        )
    ensure_web_grants()
    cmd, brief_ref = fit_command(exe, prompt, args, policy, work_dir, extra_dirs)
    return run(cmd, work_dir, extra_dirs, policy, args.timeout_min * 60 + 30, brief_ref,
               args.model)


if __name__ == "__main__":
    sys.exit(main())
