"""PostToolUse hook: after a wrapper call, surface an account-type error to the user at once.

Fires for Bash and PowerShell calls in the main session and inside subagents. Prints a decision
only when the command ran glm-run.py or agy-run.py and its output carries such an error.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from errors import account_error  # noqa: E402

WRAPPER = re.compile(r"(glm|agy)-run\.py")


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    match = WRAPPER.search(command)
    if not match:
        return 0
    response = payload.get("tool_response") or {}
    text = f"{response.get('stdout') or ''}\n{response.get('stderr') or ''}" if isinstance(response, dict) else str(response)
    error = account_error(text)
    if not error:
        return 0
    worker = match.group(1)
    note = f"workers: {worker} reported an account/access error: {error}"
    print(json.dumps({
        "systemMessage": note + " — the worker task stops here; fix the account or VPN, then ask to retry.",
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": note + ". Stop this worker task without retrying and put this error "
                                        "in the first line of your next message to the user (or of "
                                        "your report, if you are a subagent).",
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
