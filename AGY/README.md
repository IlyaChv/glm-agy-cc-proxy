# AGY — the agy wrapper

`AGY/agy-run.py` is the wrapper that delegates one self-contained task to the Antigravity CLI
(`agy`) on the Google AI Pro quota. It takes any request, in any directory, git or not. It is part of the Claude Code plugin `workers` and runs from
this repository, with no installed copy: the driver calls
`python "${CLAUDE_PLUGIN_ROOT}/AGY/agy-run.py" ...`, the same contract as `GLM/glm-run.py`. How
to delegate, what a call costs, and how to write the brief live in the `agy` skill
(`skills/agy/`). The code both wrappers share (directory guard, pre-call snapshot and change
report, process cleanup, payload parsing) is in `lib/workers_common.py`; `python -m unittest
discover -s tests` exercises it without calling agy.

Before a call that can write, each `--dir` and `--add-dir` is snapshotted into a shadow git
repository under `%LOCALAPPDATA%\workers\snapshots` (kept 7 days; a tree over 20,000 files runs
without one, with a warning; `.gitignore`d files are not in it). Afterwards the wrapper prints the
changed paths against the snapshot and the command that undoes exactly agy's changes, leaving the
user's own uncommitted work as it was. No git and no clean tree are required. `--force` skips the
snapshot.

Web: before every call the wrapper adds `read_url(*)` to `permissions.allow` in agy's settings,
because agy rewrites that file itself. `search_web(*)` was tried and agy dropped it as unknown.
Web research therefore needs no `--allow-shell`.

Exit codes: **0** success; **1** agy failed or reported an error; **2** refused before any call
(bad arguments, forbidden directory, bad or non-UTF-8 prompt file, missing binary, command line
too long); **3** timeout.

`--no-tools` is a read-only reasoning call: `--mode plan` with `--sandbox`, no accept-edits and no
`--dangerously-skip-permissions`. Nothing is written, so the snapshot and the change report are
skipped; combining it with `--allow-shell`, `--mode accept-edits` or `--no-sandbox` is refused.

From processes the Claude Code desktop app's agent starts, agy fails Google's eligibility check;
see `docs/incidents.md`, 2026-10-17, for the workaround.

## Known limits of the guard

The snapshot is the wrapper's work; the limits below are not closed by it. The first four live in
agy's own settings, `~/.gemini/antigravity-cli/settings.json`, which this repo versions nothing of
and edits only to add `read_url(*)` — and which agy rewrites itself, so values written into it do
not necessarily survive the next run. The fifth (agy's stderr) is the wrapper's own and stays open
by choice:

- **`permissions.allow` is inert while `--allow-shell` bypasses it, and too broad to become the control.** While
  a call passes `--dangerously-skip-permissions` (`--allow-shell`), the list is bypassed
  entirely; if that flag is ever dropped, entries such as `command(powershell)`, `command(&)`,
  `npx`, `winget` and `Remove-Item` become the control and grant nearly everything. What would
  close it: reducing the list to the specific commands actually needed, before anything relies
  on it as a boundary.
- **`trustedWorkspaces` trusts only agy's own install directory.** No project
  directory, and nothing ever passed as `--dir`, is trusted, so tightening workspace access
  would break delegated calls instead of scoping them. What would close it: deciding which of
  `trustedWorkspaces` and workspace access is the intended control, and making the other
  consistent with it.
- **The OAuth session is protected by policy, not mechanism.** AGENTS.md rule 5
  ("Do not open, print, copy, or commit `~/.gemini/oauth_creds.json`, and do not build anything
  that reads it.") binds a cooperative agent and nothing else.
  Deny rules in agy's settings do outrank allow, and have been added and tested, but agy
  rewrites that file on its own, so the fence is only as durable as the rewrite allows. What
  would close it: a deny rule that survives agy's rewrite, or `--sandbox` (which blocks
  sensitive files) on every call.
- **agy is not confined to `--dir`.** The snapshot only covers files inside `--dir` and
  `--add-dir` that their `.gitignore` does not exclude; `allowNonWorkspaceAccess: false` cannot be
  pinned because agy rewrites its own settings file on every run. Accepted: the wrapper reports
  what changed rather than preventing agy from reaching outside the workspace.
- **agy's stderr is bounded but not redacted.** `echo_stderr` caps what reaches the
  transcript at 4000 chars, the same as `glm-run.py`, but does not scrub it: a credential
  echoed by a failing tool call inside that window still reaches the transcript.

One more, in the same spirit: **"delegation goes through the skill" is convention only.**
The permission entry approves the wrapper command whether or not the skill was
loaded, and from any session — nothing technical enforces the skill-first order.

## The plugin, its junction and permissions

Outside this repo, and just as much part of the system:

- `~/.claude/skills/workers` — a junction to this repository, through which Claude Code loads it
  in place as the plugin `workers@skills-dir`. The plugin is off by default and turned on per
  project with `claude plugin enable workers@skills-dir --scope local`, run in that project
  (`disable` turns it off); the `workers:agy` skill and the `workers:agy-driver` agent exist only where it is on. The
  content is edited here, never through the junction path; run `/reload-plugins` after an edit.
- `~/.claude/settings.json` — `permissions.allow` entries naming
  `python "C:/Users/HOME/.claude/skills/workers/AGY/agy-run.py"` (and the same for
  `GLM/glm-run.py` and `scripts/check.py`), in both slash styles, so the wrapper runs without a
  prompt. An entry is matched against the command text, so a call has to be spelled through that
  path; `python AGY/agy-run.py` from the repo root prompts. It constrains no argument, which is
  why the wrapper checks `--dir` itself.
- `~/.gemini/antigravity-cli/settings.json` — agy's own model, permissions, workspace trust (see
  "Known limits of the guard" above).

To check that agy (and GLM) answer right now: `/workers:check` in a session, or
`python scripts/check.py` from the repo root — one tiny call each, one `OK` / `ACCOUNT` / `DOWN`
line per worker. The wrapper can still be run directly for a manual test.
