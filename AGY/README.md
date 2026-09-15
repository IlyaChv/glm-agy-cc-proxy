# AGY — the agy wrapper

`AGY/agy-run.py` is the versioned source of the wrapper that delegates one self-contained task
to the Antigravity CLI (`agy`) on the Google AI Pro quota. The call goes to the installed copy
at `~/.claude/bin/agy-run.py` — the path the permission entry allow-lists — so after editing
the source here, copy it over, the same contract as `GLM/glm-run.py`. How to delegate, what a
call costs, and how to write the brief live in the `agy` skill (`.claude/skills/agy/`).

## Known limits of the guard

The clean-tree guard is the wrapper's work; these three limits are not. They live in agy's own
settings, `~/.gemini/antigravity-cli/settings.json`, which this repo neither versions nor edits
— and which agy rewrites itself, so values written into it do not necessarily survive the next
run. They are recorded here rather than fixed because no change to the wrapper closes them:

- **SEC-2 — `permissions.allow` is inert today and too broad to be tomorrow's control.** While
  a call passes `--dangerously-skip-permissions` (`--allow-shell`), the list is bypassed
  entirely; if that flag is ever dropped, entries such as `command(powershell)`, `command(&)`,
  `npx`, `winget` and `Remove-Item` become the control and grant nearly everything. What would
  close it: reducing the list to the specific commands actually needed, before anything relies
  on it as a boundary.
- **DOC-6 — `trustedWorkspaces` trusts only agy's own install directory.** No project
  directory, and nothing ever passed as `--dir`, is trusted, so tightening workspace access
  would break delegated calls instead of scoping them. What would close it: deciding which of
  `trustedWorkspaces` and workspace access is the intended control, and making the other
  consistent with it.
- **ARC-3 — the OAuth session is protected by policy, not mechanism.** AGENTS.md rule 5
  ("never touch `~/.gemini/oauth_creds.json`") binds a cooperative agent and nothing else.
  Deny rules in agy's settings do outrank allow, and have been added and tested, but agy
  rewrites that file on its own, so the fence is only as durable as the rewrite allows. What
  would close it: a deny rule that survives agy's rewrite, or `--sandbox` (which blocks
  sensitive files) on every call.
- **SEC-1 — agy is not confined to `--dir`.** The clean-tree guard only covers git-tracked
  files inside `--dir` and `--add-dir`; `allowNonWorkspaceAccess: false` cannot be pinned
  because agy rewrites its own settings file on every run. Accepted: the guard reports what
  changed rather than preventing agy from reaching outside the workspace.

- **SEC-5 — agy's stderr is bounded but not redacted.** `echo_stderr` caps what reaches the
  transcript at 4000 chars, the same as `glm-run.py`, but does not scrub it: a credential
  echoed by a failing tool call inside that window still reaches the transcript.

One more, in the same spirit: **"delegation goes through the skill" is convention only**
(DOC-4). The permission entry approves the wrapper command whether or not the skill was
loaded, and from any session — nothing technical enforces the skill-first order.
