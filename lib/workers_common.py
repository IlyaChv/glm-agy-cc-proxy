"""Code shared by GLM/glm-run.py and AGY/agy-run.py.

Directory and prompt-file guards, the pre-call snapshot and change report, the child's
environment scrub, process-tree cleanup, stderr echo, and JSON payload parsing. Every
function that prints takes `prog` ("glm-run" / "agy-run") so its lines keep the prefix
scripts/errors.py keys on.
"""

import json
import os
import subprocess
import sys

# Exit codes, the same for both wrappers.
EXIT_OK = 0
EXIT_FAILED = 1     # the worker failed or reported an error
EXIT_REFUSED = 2    # refused before any call: bad args, forbidden dir, bad prompt file
EXIT_TIMEOUT = 3    # the worker did not return within the wall-clock limit

# Pre-call snapshots (the revert point for any directory), kept for a week.
SNAPSHOT_ROOT = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "workers", "snapshots")
SNAPSHOT_KEEP_DAYS = 7
SNAPSHOT_MAX_FILES = 20000

# Cap on the child's stderr copied into the caller's transcript.
MAX_STDERR_CHARS = 4000

# Directories a delegated call must never be pointed at, whatever the flags say: they hold
# credentials, agent configuration or application state. The permission entry that lets a
# wrapper run unprompted matches the program path only, so this is the floor under --dir.
# AppData is not blanket-forbidden: AppData/Local/Temp is where scratch working copies live.
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


def utf8_stdio():
    """Force UTF-8 on stdout/stderr; under redirection Windows gives them the console codepage."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def die(message, code):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


def refuse(message):
    die(message, EXIT_REFUSED)


def git(args, cwd):
    """Run git in `cwd`, ignoring any GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE and fsmonitor hook."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false"] + args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env,
    )


def scrubbed_env():
    """os.environ without the calling session's Anthropic and Claude Code variables.

    Host-session auth such as CLAUDE_CODE_ENTRYPOINT makes Z.AI answer 401, and none of it is
    agy's business either.
    """
    env = {
        k: v for k, v in os.environ.items()
        if not k.upper().startswith(("ANTHROPIC_", "CLAUDE_CODE_"))
    }
    env.pop("CLAUDECODE", None)
    return env


def _home():
    return os.path.normcase(os.path.realpath(os.path.expanduser("~")))


def forbidden_subpath(real, prog):
    """The FORBIDDEN_SUBPATHS entry `real` (normcased) sits inside (or equals), or None.

    A UNC path is refused outright: realpath maps neither an administrative share
    (\\\\localhost\\C$\\...) nor a subst drive onto the drive-letter form.
    """
    home = _home()
    if os.path.normcase(real).startswith("\\\\"):
        refuse("{}: refused, {} is a UNC path; use the drive-letter form.".format(prog, real))
    home_drive = os.path.splitdrive(home)[0]
    for rel in FORBIDDEN_SUBPATHS:
        forbidden = os.path.normcase(os.path.realpath(os.path.join(home, *rel.split("/"))))
        inside = real == forbidden or real.startswith(forbidden + os.sep)
        if not inside and os.path.splitdrive(real)[0] != home_drive:
            # A subst drive gives the same directory another letter; samefile sees through
            # it and raises when either path is missing.
            try:
                inside = os.path.samefile(real, forbidden)
            except OSError:
                pass
        if inside:
            return rel
    return None


def check_prompt_file_allowed(path, prog):
    """Refuse a --prompt-file under the forbidden directories: its contents leave the machine."""
    rel = forbidden_subpath(os.path.normcase(os.path.realpath(os.path.abspath(path))), prog)
    if rel:
        refuse(
            "{}: refused, --prompt-file is inside {}, which holds credentials "
            "or agent configuration.\n         If you truly meant it, move the file "
            "out first.".format(prog, rel)
        )


def read_prompt(prompt, prompt_file, prog):
    """The brief from --prompt or --prompt-file, stripped; refuses a missing, unreadable or empty one."""
    if prompt_file:
        if not os.path.isfile(prompt_file):
            refuse("{}: no such prompt file: {}".format(prog, prompt_file))
        check_prompt_file_allowed(prompt_file, prog)
        try:
            with open(prompt_file, encoding="utf-8-sig") as fh:
                prompt = fh.read()
        except UnicodeDecodeError as exc:
            refuse(
                "{}: refused, --prompt-file {} is not valid UTF-8 ({}). Save it as UTF-8 "
                "and retry.".format(prog, prompt_file, exc)
            )
    prompt = (prompt or "").strip()
    if not prompt:
        refuse("{}: the prompt is empty".format(prog))
    return prompt


def check_dir_allowed(work_dir, prog, roots_var):
    """Refuse a working directory no delegated task should ever have. --force does not lift it."""
    home = _home()
    real = os.path.normcase(os.path.realpath(work_dir))

    if real == home:
        refuse(
            "{}: refused, --dir is the home directory itself. Point it at a "
            "project, not at everything you own.".format(prog)
        )

    # A drive root or any ancestor of home hands the worker every forbidden directory at once.
    parents = []
    parent = os.path.dirname(home)
    while parent and parent != os.path.dirname(parent):
        parents.append(parent)
        parent = os.path.dirname(parent)
    if os.path.splitdrive(real)[1] in ("", os.sep) or real in parents:
        refuse(
            "{}: refused, --dir is a drive root or a parent of the home "
            "directory. Point it at a project, not at everything on the machine.".format(prog)
        )

    rel = forbidden_subpath(real, prog)
    if rel:
        refuse(
            "{}: refused, --dir is inside {}, which holds credentials or "
            "agent configuration.\n         No delegated task needs to work "
            "there. Point --dir at a project directory instead.".format(prog, rel)
        )

    # A directory that contains a forbidden one (~/AppData holds AppData/Roaming) hands it over too.
    for rel in FORBIDDEN_SUBPATHS:
        forbidden = os.path.normcase(os.path.realpath(os.path.join(home, *rel.split("/"))))
        if forbidden.startswith(real + os.sep):
            refuse(
                "{}: refused, --dir contains {}, which holds credentials or "
                "agent configuration.\n         Point --dir at a project directory "
                "instead.".format(prog, rel)
            )

    # Optional per-machine narrowing, semicolon separated since Windows paths contain colons.
    roots = os.environ.get(roots_var, "").strip()
    if roots:
        allowed = [
            os.path.normcase(os.path.realpath(r.strip())) for r in roots.split(";") if r.strip()
        ]
        if not any(real == a or real.startswith(a + os.sep) for a in allowed):
            refuse(
                "{}: refused, --dir is outside {}.\n"
                "         dir:   {}\n         roots: {}".format(
                    prog, roots_var, real, "; ".join(allowed))
            )


def head_commit(d):
    """`git rev-parse HEAD` in d, or None (no commits yet, or not a repository)."""
    res = git(["rev-parse", "HEAD"], d)
    return res.stdout.strip() if res.returncode == 0 else None


def _shadow(snap, work_dir, args):
    """git on a shadow repository whose work tree is work_dir; the project's own .git is untouched."""
    return git(["--git-dir=" + snap, "--work-tree=" + work_dir,
                "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
                "-c", "user.name=workers", "-c", "user.email=workers@localhost"] + args, work_dir)


def _count_files(work_dir, limit):
    """Files under work_dir outside .git, counted up to limit + 1."""
    n = 0
    for _root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        n += len(files)
        if n > limit:
            break
    return n


def _prune_snapshots(keep_days=SNAPSHOT_KEEP_DAYS):
    """Delete snapshots older than keep_days; a failure here never blocks a call."""
    import shutil
    import time
    cutoff = time.time() - keep_days * 86400
    try:
        for name in os.listdir(SNAPSHOT_ROOT):
            path = os.path.join(SNAPSHOT_ROOT, name)
            if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def take_snapshots(dirs, prog):
    """Snapshot each dir into a shadow git repository; {dir: snapshot path or None}.

    This is the safety net for any directory - a git repository with uncommitted work, or no
    repository at all: whatever the worker changes can be listed and reverted afterwards
    without touching the project's own history. Files the dir's .gitignore excludes are not
    in the snapshot. A tree over SNAPSHOT_MAX_FILES, or a failed snapshot, runs without a net
    and says so.
    """
    import time
    _prune_snapshots()
    try:
        os.makedirs(SNAPSHOT_ROOT, exist_ok=True)
    except OSError:
        pass
    stamp = time.strftime("%Y%m%d-%H%M%S")
    snaps = {}
    for i, d in enumerate(dirs):
        if _count_files(d, SNAPSHOT_MAX_FILES) > SNAPSHOT_MAX_FILES:
            sys.stderr.write(
                "{}: warning: {} holds over {} files, too many to snapshot; the worker runs "
                "without a revert point there.\n".format(prog, d, SNAPSHOT_MAX_FILES))
            snaps[d] = None
            continue
        snap = os.path.join(SNAPSHOT_ROOT, "{}-{}-{}".format(stamp, os.getpid(), i))
        steps = (["init", "-q"], ["add", "-A"],
                 ["commit", "-q", "--allow-empty", "--no-verify", "-m", "before " + prog])
        for step in steps:
            res = _shadow(snap, d, step)
            if res.returncode != 0:
                first = (res.stderr or "").strip().splitlines()
                sys.stderr.write(
                    "{}: warning: snapshot of {} failed ({}); the worker runs without a "
                    "revert point there.\n".format(prog, d, first[0] if first else step[0]))
                snap = None
                break
        snaps[d] = snap
    return snaps


def report_changes(snaps, heads_before, prog):
    """Say what the worker touched in each dir against its snapshot, and how to undo it."""
    for d, snap in snaps.items():
        before = heads_before.get(d)
        after_head = head_commit(d)
        if after_head != before:
            sys.stderr.write(
                "{}: HEAD moved in {} from {} to {} - the worker committed; `git log --stat` "
                "there shows what it did.\n".format(
                    prog, d, before or "(none)", after_head or "(none)"))
        if snap is None:
            continue
        _shadow(snap, d, ["add", "-A"])
        diff = _shadow(snap, d, ["diff", "--cached", "--name-status", "HEAD"])
        if diff.returncode != 0:
            first = (diff.stderr or "").strip().splitlines()
            sys.stderr.write("{}: warning: change report unavailable for {} ({})\n".format(
                prog, d, first[0] if first else "git diff failed"))
            continue
        touched = [line for line in diff.stdout.splitlines() if line.strip()]
        if not touched:
            sys.stderr.write("{}: no files changed in {}\n".format(prog, d))
            continue
        shown = "\n".join("         " + t for t in touched[:15])
        more = "" if len(touched) <= 15 else "\n         ... and {} more".format(
            len(touched) - 15)
        base = 'git --git-dir="{}" --work-tree="{}"'.format(snap, d)
        sys.stderr.write(
            "{}: {} path(s) changed in {} - to undo exactly the worker's changes, run:\n"
            "         {} reset -q --hard HEAD && {} clean -fdq\n{}{}\n".format(
                prog, len(touched), d, base, base, shown, more))


def kill_tree(proc, prog):
    """taskkill takes the whole tree, which proc.kill() cannot; fall back to the child alone."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10
        )
    except Exception as exc:
        sys.stderr.write("{}: taskkill failed ({}), killing the child only\n".format(prog, exc))
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def kill_on_close_job(proc, prog):
    """Put proc in a Job Object the OS kills when this wrapper exits; the handle, or None."""
    try:
        import ctypes
        from ctypes import wintypes

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        # 9 = JobObjectExtendedLimitInformation.
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        return job
    except Exception as exc:
        sys.stderr.write(
            "{}: warning: could not tie the worker to this process ({}); if this "
            "wrapper is killed, the worker keeps running\n".format(prog, exc)
        )
        return None


def run_worker(cmd, cwd, env, hard_limit, prog, input_text=None):
    """Run the worker; (returncode, stdout, stderr). On timeout kill its tree and re-raise.

    With input_text the brief goes in on stdin; without it stdin is DEVNULL.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    # Never closed here: the OS closes it when this process dies, which kills the worker.
    job = kill_on_close_job(proc, prog)  # noqa: F841
    try:
        out, err = proc.communicate(input=input_text, timeout=hard_limit)
    except subprocess.TimeoutExpired:
        kill_tree(proc, prog)
        raise
    finally:
        if proc.poll() is None:
            kill_tree(proc, prog)
    return proc.returncode, out, err


def echo_stderr(err, prog):
    """Copy the child's stderr through, truncated in the middle (not scrubbed)."""
    if not err:
        return
    if len(err) <= MAX_STDERR_CHARS:
        sys.stderr.write(err)
        return
    half = MAX_STDERR_CHARS // 2
    sys.stderr.write(
        err[:half]
        + "\n... {}: {} chars of worker stderr omitted ...\n".format(
            prog, len(err) - MAX_STDERR_CHARS
        )
        + err[-half:]
    )


def parse_payload(raw):
    """The last complete JSON object in the worker's stdout, or None.

    Tries the whole text first, then each line that starts with `{` (after leading
    whitespace), last to first, and accepts only an object that runs to the end of the
    stream: trailing text makes the parse fail by design, so a truncated or mixed stream is
    not mistaken for a payload.
    """
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
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


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_number(value, default=0):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def as_text(value):
    """A payload answer field as text: None is empty, a non-string is its JSON."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
