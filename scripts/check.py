"""Availability check for the workers: one tiny call to each, through its wrapper.

    python check.py            run both, print one line per worker, exit 1 if any is down
    python check.py --session  SessionStart hook: skip a worker that passed in the last hour;
                               on a failure print it to stderr and exit 2, which wakes the session

A call costs a few thousand input tokens on the worker's own quota (Z.AI, Google), nothing on
Anthropic. The probe runs in a scratch directory under %TEMP%, never in the project.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from errors import account_error  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path(tempfile.gettempdir()) / "workers-plugin-data")
FRESH_SECONDS = 3600
PROMPT = "Привет! Ты кто?"


def probe_dir():
    d = Path(tempfile.gettempdir()) / "workers-probe"
    d.mkdir(exist_ok=True)
    return str(d)


COMMANDS = {
    "glm": lambda d: [sys.executable, str(ROOT / "GLM" / "glm-run.py"), "--no-tools",
                      "--dir", d, "--timeout-min", "2", "--prompt", PROMPT],
    "agy": lambda d: [sys.executable, str(ROOT / "AGY" / "agy-run.py"), "--mode", "plan",
                      "--dir", d, "--timeout-min", "2", "--prompt", PROMPT],
}


def probe(name):
    start = time.time()
    try:
        r = subprocess.run(COMMANDS[name](probe_dir()), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=200)
        out, rc = (r.stdout or "") + "\n" + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired:
        out, rc = "check: no answer within 200 s", 124
    ok = rc == 0 and bool((r.stdout or "").strip()) if rc != 124 else False
    account = None if ok else account_error(out)
    tail = [line.strip() for line in out.splitlines() if line.strip()]
    detail = account or (tail[-1][:300] if tail else f"exit {rc}")
    return {"ok": ok, "account": bool(account), "detail": "" if ok else detail,
            "seconds": round(time.time() - start), "at": time.time()}


def load_status():
    try:
        return json.loads((DATA / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_status(status):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")


def main():
    session = "--session" in sys.argv
    status = load_status()
    names = [n for n in COMMANDS
             if not (session and status.get(n, {}).get("ok")
                     and time.time() - status[n].get("at", 0) < FRESH_SECONDS)]
    with ThreadPoolExecutor(len(COMMANDS)) as pool:
        for name, result in zip(names, pool.map(probe, names)):
            status[name] = result
    save_status(status)

    down = {n: s for n, s in status.items() if n in COMMANDS and not s.get("ok")}
    if session:
        if not down:
            return 0
        for name, s in down.items():
            kind = "account/access error" if s.get("account") else "failed"
            print(f"workers plugin: {name} {kind}: {s['detail']}", file=sys.stderr)
        print("Tell the user this now, first line of your next message; account and VPN errors "
              "are fixed by hand. /workers:check re-runs the check.", file=sys.stderr)
        return 2
    for name in COMMANDS:
        s = status[name]
        state = "OK" if s["ok"] else ("ACCOUNT" if s.get("account") else "DOWN")
        print(f"{name:4} {state:8} {s['seconds']:>3}s  {s['detail']}")
    return 1 if down else 0


if __name__ == "__main__":
    sys.exit(main())
