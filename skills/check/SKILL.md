---
name: check
description: Check that the GLM and agy workers are reachable right now — one tiny call to each through its wrapper. Use when the user asks whether the workers work, before the first delegation of a session when no check has reported, or after the user says an account or VPN problem is fixed.
---

Run:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check.py"
```

It prints one line per worker — `OK`, `ACCOUNT` (an account, eligibility, quota, auth or region
error) or `DOWN` (anything else) — with the time taken and the error line. Relay the lines to the
user as they are. For `ACCOUNT`, say that it is the user's to fix (the account or the VPN region)
and that the worker is not used until a re-check passes. Each probe costs a few thousand input
tokens on the worker's own quota and nothing on Anthropic.
