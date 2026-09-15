# Consolidated findings

Source shards: A1 (`agy-run.py`), A2 (contract docs), A3 (skill / permissions / security).
Lead consolidation: dedup, re-severity, corrections. Shard IDs kept in `from:` for traceability.

Cross-lens agreement raises confidence, never severity.

---

## NEW-1 · agy reports a task done without doing it, and the wrapper cannot tell
- found: 2026-09-13 while verifying the A1-12 fix; not from a shard
- severity: **Medium** · confidence: **High** (observed directly) · effort: Medium
- evidence — the call returned exit 0 with a plausible answer:
```
agy-run: status=SUCCESS model=gemini-3.8-flash-high in=27862 out=1385 ... 11s
done.
EXIT=0
```
  and the working tree afterwards:
```
$ ls -a
. .. .git .gitignore build local-notes.txt tracked.txt
$ cat made.txt
cat: made.txt: No such file or directory
```
- claim: the brief said to create `made.txt` with the file-writing tool. agy answered "done." and
  created nothing. Every check the wrapper has passed: status was SUCCESS, the response was
  non-empty, the child exited 0. Re-running with the target given as an absolute path produced the
  file, so the trigger looks like relative-path resolution rather than a refusal - but the failure
  mode is the point, not the cause.
- failure: a delegated write task silently does nothing, the caller reads "done", and the work is
  assumed complete. This is the same class as the empty-answer bug the wrapper was built to catch,
  and it slips through because the answer is not empty.
- fix: no reliable one from the wrapper's side - it cannot know what the brief asked for. Two
  partial mitigations are in place: the post-run change report (A1-12) prints what actually changed
  in `--dir`, so *nothing changed* after a write task is now visible; and `SKILL.md` says to check
  what agy produced rather than believe the summary. Giving absolute paths in briefs avoids the
  observed trigger.

---

## Corrections the lead made to shard output

**A3-1 REFUTED.** The shard claimed the allow-rule `Bash(python .../agy-run.py:*)` lets an
attacker chain `&& curl ...` and run it unprompted. A verifier settled it against Anthropic's
primary documentation:

> "Claude Code is aware of shell operators, so a rule like `Bash(safe-cmd *)` won't give it
> permission to run the command `safe-cmd && other-cmd`. The recognized command separators are
> `&&`, `||`, `;`, `|`, `|&`, `&`, and newlines. A rule must match each subcommand independently."
> — code.claude.com/docs/en/permissions.md

The exfiltration scenario would have stopped at the `curl` subcommand. Dropped as stated; replaced
by SEC-3, which is the narrower thing that is actually true.

**A3-6, A3-7, A3-8, A3-12 re-framed.** These four treated agy's `permissions.allow` entries
(`command(powershell)`, `command(&)`, `command(Remove-Item)`, `command(npx)`, `command(winget)`)
as the mechanism that auto-approves dangerous commands. They are not. `agy --help`:
`--dangerously-skip-permissions  Auto-approve all tool permission requests without prompting`.
While the wrapper passes that flag — which it does on every call with tools — the allow-list is
bypassed entirely and its contents change nothing. The real state is broader than the shard
described, not narrower. Merged into SEC-2.

---

## SEC — safety of the delegation

### SEC-1 · The clean-tree guard protects only `--dir`; agy is not confined to `--dir`
- from: A1-3 + A3-4 (found independently by two shards)
- files: `~/.claude/bin/agy-run.py:9-18,62-85`; `~/.gemini/antigravity-cli/settings.json:2`
- severity: **High** · confidence: **High** (cross-lens agreement) · effort: Low
- evidence:
```
  - refuses to run on a dirty or non-git tree, which is the only thing standing
    between --dangerously-skip-permissions and unrecoverable edits.
```
```
  "allowNonWorkspaceAccess": true,
```
- claim: `check_clean_tree` runs `git status --porcelain` inside `--dir` only. `cwd=work_dir` sets
  the child's working directory; it does not sandbox filesystem access. With
  `allowNonWorkspaceAccess: true`, agy's own file tools have no workspace boundary either. So the
  wrapper's central promise — any outcome is revertible with `git checkout .` — holds for exactly
  one directory and nothing else.
- failure: a brief that names or infers an absolute path outside `--dir` (a sibling repo on the
  Desktop, `~/.claude/settings.json`, `~/.gemini/`) gets edited by agy. Nothing checked those
  paths, nothing can revert them, and the wrapper still reports a clean run.
- fix: set `allowNonWorkspaceAccess: false`, and say in the docstring that the guarantee is scoped
  to `--dir`.
- closed: Accepted 2026-09-15 as a known limit, documented in AGY/README.md; the guard's scope is stated in --help and the docstring (929032a). Not closable from the wrapper.

### SEC-2 · agy's `permissions.allow` is bypassed today and too broad to be tomorrow's control
- from: A3-6, A3-7, A3-8, A3-12, merged and re-framed by the lead
- file: `~/.gemini/antigravity-cli/settings.json:10-25`
- severity: **Medium** · confidence: **High** · effort: Low
- evidence:
```
      "command(powershell)",
      "command(&)",
      "command(Remove-Item)",
      "command(npx)",
      "command(winget)",
```
- claim: two problems in sequence. Today the list is inert: `--dangerously-skip-permissions`
  approves everything regardless of it. And if the project moves to the supported alternative
  (see ARC-1), this list becomes the control — and these five entries are not narrow permissions.
  `&` is PowerShell's call operator, `powershell` is the interpreter itself, `npx` and `winget`
  fetch and execute arbitrary third-party code, `Remove-Item` has no path or `-Recurse` bound.
- failure: whoever drops the blanket flag believing the allow-list is a meaningful boundary gets
  approximately the same blast radius they thought they had removed.
- fix: reduce to the specific commands actually needed before relying on the list for anything.
- closed: Recorded 2026-09-15 as a known limit in AGY/README.md; not closable from the wrapper.

### SEC-3 · An allow-listed call has unconstrained `--dir` and `--prompt`
- from: the A3-1 verifier's residual risk (replaces the refuted claim)
- file: `~/.claude/settings.json:5`
- severity: **Medium** · confidence: **High** · effort: Medium
- evidence:
```
      "Bash(python C:/Users/cupik/.claude/bin/agy-run.py:*)"
```
- claim: `:*` constrains the program path, not the arguments. A single unsplit subcommand such as
  `python .../agy-run.py --dir C:/Users/cupik/.gemini --prompt "..."` matches the rule and runs
  with no prompt. The wrapper does not restrict what `--dir` may point at — only that it is a
  clean git repository, which `~/.gemini` is not, so that call would be refused by the guard.
  But any *other* clean repository on the machine is reachable unprompted.
- failure: a delegated call is aimed at a directory the human never intended to expose, and the
  first they see of it is the usage line after the fact.
- fix: none free of cost. Either accept it and say so, or have `agy-run.py` require `--dir` to sit
  under an allow-listed root. Note that AGENTS.md rule 5 (never touch `oauth_creds.json`) is the
  only thing covering the worst case, and it is a policy, not a mechanism.
- closed: Already present in the wrapper as versioned at c8b466e; refactored into forbidden_subpath (shared by check_dir_allowed and the new check_prompt_file_allowed) in 929032a.

### SEC-4 · The clean-tree guard cannot see gitignored files
- from: A1-2
- file: `~/.claude/bin/agy-run.py:62-85`
- severity: **Medium** · confidence: **High** · effort: Low
- evidence:
```
    status = git(["status", "--porcelain"], work_dir)
```
- claim: `git status --porcelain` without `--ignored` never reports ignored paths. They are
  invisible to the check before the run and invisible to `git checkout .` after it.
- failure: agy modifies or deletes a gitignored local config or scratch file inside `--dir`. The
  tree reads clean before and after; the file is gone with no history to restore it from.
- fix: name the limit in the refusal text and the docstring. Actually protecting ignored files
  needs a backup step, which is larger than this script.
- closed: Already present in the wrapper as versioned at c8b466e; warn_about_ignored is unchanged through 929032a.

### SEC-5 · agy's stderr is copied into the transcript unfiltered and unbounded
- from: A3-9
- file: `~/.claude/bin/agy-run.py:180-181`
- severity: **Low** · confidence: **Medium** · effort: Low
- evidence:
```
    if proc.stderr:
        sys.stderr.write(proc.stderr)
```
- claim: whatever agy's process writes to stderr — including output from tool calls it made while
  auto-approved — is copied verbatim into the calling session with no truncation or scrubbing.
- failure: a tool call that errors near a credential echoes an argument or a path into the Claude
  Code transcript. AGENTS.md rule 3 treats that as compromise the moment it happens.
- fix: cap the echoed length and name stderr as untrusted passthrough in the docstring.
- closed: Bounded 2026-09-15 (echo_stderr, 4000 chars, as in glm-run.py) but not redacted; recorded as a known limit in AGY/README.md. Still open as to redaction.

---

## COR — correctness and robustness of `agy-run.py`

### COR-1 · Success path never checks agy's own exit code
- from: A1-1 · file: `~/.claude/bin/agy-run.py:183-213`
- severity: **Medium** · confidence: **High** · effort: Low
- evidence:
```
    status = payload.get("status", "UNKNOWN")
```
- claim: `proc.returncode` is read only in the "no JSON on stdout" branch. Once any `{` is found
  and the JSON parses, success is decided purely from `status` and `response`.
- failure: agy flushes a valid `{"status":"SUCCESS",...}` and then crashes during cleanup. The
  wrapper prints the answer and exits 0; a crashed run is reported as clean. This is precisely the
  failure class the wrapper exists to prevent.
- fix: after the payload parses, warn (or fail) when `proc.returncode != 0`.
- closed: Closed before 2026-09-15; confirmed in the tree on 2026-09-15: proc.returncode checked after the payload parses (agy-run.py, run/main).

### COR-2 · Timeout kills agy but not the processes agy spawned
- from: A1-4 · file: `~/.claude/bin/agy-run.py:163-178`
- severity: **Medium** · confidence: **Medium** · effort: Medium
- claim: on Windows `subprocess.run`'s timeout terminates the direct child only; no Job Object, so
  grandchildren survive.
- failure: the hard wall clock fires mid-tool-call. The wrapper tells the caller nothing happened,
  while a process agy started keeps writing into `--dir`.
- fix: on `TimeoutExpired`, kill the tree (`taskkill /PID <pid> /T /F`), which needs `Popen` to
  keep the pid.
- closed: Already present in the wrapper as versioned at c8b466e; refactored into kill_tree in 929032a.

### COR-3 · `raw.find("{")` assumes stdout holds nothing but the payload
- from: A1-5 · file: `~/.claude/bin/agy-run.py:183-192`
- severity: **Low** · confidence: **Medium** · effort: Low
- claim: it finds the first brace anywhere in stdout, not the start of the JSON.
- failure: a future agy build prints a banner containing `{` before the result; parsing starts
  mid-diagnostic and fails with a confusing message instead of reading the real payload. AGENTS.md
  itself notes this CLI is on a weekly cadence and its flags have already moved once.
- fix: try `json.loads(raw)` whole first, fall back to the brace heuristic.
- closed: Closed 2026-09-15 in 929032a: the payload is the last complete JSON object in stdout, parsed with json.JSONDecoder; raw.find("{") is gone.

### COR-4 · `git()` decodes with strict UTF-8 while the agy call does not
- from: A1-6 · file: `~/.claude/bin/agy-run.py:56-59`
- severity: **Low** · confidence: **Medium** · effort: Low
- evidence:
```
        ["git"] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8"
```
- claim: no `errors=` argument, so it defaults to strict, unlike the agy call which passes
  `errors="replace"`.
- failure: a filename in `--dir` in a legacy codepage makes `git status` output undecodable; the
  user gets a raw `UnicodeDecodeError` traceback instead of one of the script's refusal messages.
- fix: add `errors="replace"`.
- closed: Already present in the wrapper as versioned at c8b466e; unchanged in git() through 929032a.

### COR-5 · A broken `AGY_BIN` override is silently ignored
- from: A1-9 · file: `~/.claude/bin/agy-run.py:41-53`
- severity: **Low** · confidence: **High** · effort: Low
- claim: if `AGY_BIN` is set but is not a file, the function falls through to the `LOCALAPPDATA`
  guess and then `PATH` with no message.
- failure: someone pins a specific agy build to avoid a known bug, mistypes the path, and silently
  runs a different build.
- fix: warn to stderr before falling through.
- closed: Closed 2026-09-15 in 929032a: a AGY_BIN that is not an executable file exits with an error naming the value instead of falling back.

### COR-6 · `--timeout-min` accepts zero and negative values
- from: A1-11 · file: `~/.claude/bin/agy-run.py:107,162`
- severity: **Low** · confidence: **High** · effort: Low
- claim: `type=int` with no range check. `--timeout-min -10` yields `hard_limit = -570`, passed
  straight to `subprocess.run(timeout=...)`.
- fix: one line — reject values `<= 0` after parsing.
- closed: Already present in the wrapper as versioned at c8b466e; reworded from sys.exit to ap.error in main() in 929032a.

### COR-7 · The 30 000-char guard counts characters, not the quoted command line
- from: A1-10 · file: `~/.claude/bin/agy-run.py:36-38,130-137`
- severity: **Low** · confidence: **Low** · effort: Low
- claim: the margin to the 32 767 `CreateProcess` limit is 2 767 chars, but Windows argv quoting
  expands every embedded `"` and doubles backslashes before a quote.
- failure: a brief near the threshold that quotes code or JSON heavily overruns the real limit and
  fails at OS level with an error the script does not explain.
- fix: widen the margin, or say in the error text that quote-heavy briefs should use
  `--prompt-file` well before the limit.
- closed: Closed 2026-09-15 in 929032a: the limit is measured on subprocess.list2cmdline(cmd), the quoted command line, not on the prompt's raw length.

### COR-8 · Invalid UTF-8 from agy is replaced with no indication
- from: A1-7 · file: `~/.claude/bin/agy-run.py:169-170`
- severity: **Low** · confidence: **Low** · effort: Low
- claim: `errors="replace"` silently substitutes U+FFFD; nothing reports that the text was altered.
- fix: warn once when `"\ufffd" in raw`.
- closed: Already present in the wrapper as versioned at c8b466e; unchanged, inline in main(), through 929032a.

### Noted, not a finding
**A1-12** — the clean-tree check is a point-in-time guarantee; the tree can change between the
check and agy's first write. Real, but closing it needs locking or per-tool-call rechecks, which
is out of proportion to a 230-line script. Record it as a stated limitation.

---

## DOC — contract, skill, and configuration accuracy

### DOC-1 · The contract tells agents to commit on `main`; the branch is `master`
- from: A2-1, **verified by the lead** · file: `AGENTS.md:236-237`
- severity: **Medium** · confidence: **High** · effort: Low
- evidence:
```
- Local-only repository, no remote. Commit on `main`; a branch only when a change is speculative
```
- lead verification: `git symbolic-ref --short HEAD` → `master`; `git branch -a` → only `master`;
  `git config init.defaultBranch` → `master`.
- failure: an agent runs `git checkout main`, fails, or creates a second branch. The hand-over
  summary of the build session already repeated the error and said the commits were on `main`.
- fix: one word in AGENTS.md, or rename the branch — whichever the human prefers.
- closed: Closed before 2026-09-15; confirmed in the tree on 2026-09-15: AGENTS.md Git section says master.

### DOC-2 · `CLAUDE.md` instructs passing an `effort` per subagent call; no such parameter exists
- from: A2-3, **verified by the lead** · file: `CLAUDE.md:78-87`
- severity: **Medium** · confidence: **High** · effort: Low
- evidence:
```
Pass the model and effort per call from the table below; without them the subagent inherits this
session's.
```
- lead verification: the `Agent` tool accepts `description`, `isolation`, `model`, `prompt`,
  `run_in_background`, `subagent_type`. There is no `effort` field. `set_session_effort` targets
  a separate existing session, not a subagent being spawned.
- failure: it happened in this very audit. The human asked for shards on "sonnet 5 high"; model
  was settable, effort was not, and the shards ran at the session's inherited effort. A rule that
  cannot be followed is worse than no rule, because it is followed halfway in silence.
- fix: drop the effort column's instruction, or state that effort is not per-call controllable and
  the values are informational until the tool exposes it.
- closed: Closed before 2026-09-15; confirmed in the tree on 2026-09-15: CLAUDE.md states the Agent tool takes model but no effort.

### DOC-3 · The delegation rule is duplicated across both always-loaded files
- from: A2-5 · files: `AGENTS.md:152-158`; `CLAUDE.md:58-73`
- severity: **Medium** · confidence: **Medium** · effort: Low
- claim: the same rule and near-identical "why" text appear in both files, which every session
  loads together. `CLAUDE.md:13-14` names this exact pattern as harmful: "Do not copy rules into
  this file. A second file with overlapping rules drifts within weeks."
- failure: ~16 of `CLAUDE.md`'s lines restate content already loaded, paid for on every turn, and
  a later edit to one copy diverges silently from the other.
- fix: keep the criteria and the why in `AGENTS.md`; leave `CLAUDE.md` the model table and a
  pointer.
- closed: Closed 2026-09-15 on agent/audit-agy-fixes: the duplicated sentences were removed from CLAUDE.md, which now points at the AGENTS.md section.

### DOC-4 · "Delegation runs through the skill" has no enforcement
- from: A2-4 · files: `CLAUDE.md:40-42`; `~/.claude/settings.json:1-8`
- severity: **Medium** · confidence: **High** · effort: Low
- claim: the permission entry auto-approves the Bash command itself; it cannot know whether the
  skill was loaded first. The skill's own instruction is to run that identical command.
- failure: a session skips the skill and calls the wrapper directly. It runs unprompted exactly as
  if the skill had been used, minus the cost and failure-mode framing, and nothing notices.
- fix: say plainly that it is a convention with no technical gate, or move the cost and
  failure-handling guidance into `agy-run.py --help`, where it cannot be skipped.
- closed: Closed 2026-09-15 in 929032a: recorded in AGY/README.md that "delegation goes through the skill" is convention only, with no technical enforcement.

### DOC-5 · The wrapper's docstring claim is contradicted by its own `--force` flag
- from: A1-8 · file: `~/.claude/bin/agy-run.py:17-18,106,125-126`
- severity: **Medium** · confidence: **High** · effort: Low
- evidence:
```
  - refuses to run on a dirty or non-git tree, which is the only thing standing
    between --dangerously-skip-permissions and unrecoverable edits.
```
- claim: `--force` removes exactly that check while leaving tools auto-approved.
- fix: add "unless `--force` is passed" to the docstring bullet.
- closed: Closed before 2026-09-15; confirmed in the tree on 2026-09-15: docstring says --force skips the check while leaving tools on.

### DOC-6 · `trustedWorkspaces` trusts agy's own install directory, not any project
- from: A3-5 · file: `~/.gemini/antigravity-cli/settings.json:28-30`
- severity: **Medium** · confidence: **High** · effort: Low
- evidence:
```
  "trustedWorkspaces": [
    "C:\\Users\\cupik\\AppData\\Local\\agy\\bin"
  ]
```
- claim: the single trusted path is agy's own binary folder — not the Desktop project, not any
  directory ever passed as `--dir`.
- failure: whoever later sets `allowNonWorkspaceAccess: false` expecting `trustedWorkspaces` to
  cover the project finds every delegated call breaking or silently losing tool access.
- fix: decide which setting is the intended control and make the other consistent with it. Relevant
  to SEC-1's fix, so do them together.
- closed: Recorded 2026-09-15 as a known limit in AGY/README.md; not closable from the wrapper.

### DOC-7 · `SKILL.md` implies oversized inline prompts are auto-converted; they hard-fail
- from: A3-10 · files: `~/.claude/skills/agy/SKILL.md:19-20`; `agy-run.py:130-137`
- severity: **Low** · confidence: **High** · effort: Low
- evidence:
```
Anything over 30 000 characters
is passed by path instead of inline, which costs agy an extra read - keep briefs shorter than that.
```
- claim: that is true only when `--prompt-file` was used. An oversized `--prompt` exits with an
  error and makes no call at all.
- fix: one sentence in `SKILL.md`.
- closed: Closed 2026-09-15 on agent/audit-agy-fixes: SKILL.md now states that an oversized inline --prompt hard-fails and is never auto-converted, and that the limit is the quoted command line.

### DOC-8 · `known-problems.md` can never load
- from: A2-2 · file: `.claude/rules/known-problems.md:1-5`
- severity: **Low** · confidence: **High** · effort: Low
- claim: the `paths:` frontmatter is still the literal placeholder `"<path/to/legacy>/**"`, so no
  file an agent opens can match it. The rule is silently inert, and `AGENTS.md:129-130` points at
  it as a live mechanism.
- fix: delete the file until a real legacy area exists, or fill `paths` the moment the first row is
  added.

### DOC-9 · `docs/adr/` and its index do not exist
- from: A2-7, **verified by the lead** · files: `AGENTS.md:8-9`; `docs/templates/adr.md:38-39`
- severity: **Low** · confidence: **High** · effort: Low
- lead verification: `docs/` contains only `templates/`.
- claim: the template says the index "is the only place the list of decisions is maintained", and
  the contract points at `docs/adr/` as a live location. Neither exists.
- fix: reword the template to "create it if absent", or scaffold an empty index.
- closed: Closed 2026-09-15: docs/adr/ exists with ADR-001-glm-endpoint-in-child-environment.md and ADR-INDEX.md.

### DOC-10 · The task-brief template requires an MR in a repo with no remote
- from: A2-6 · files: `docs/templates/task-brief.md:90-96`; `AGENTS.md:236-237`
- severity: **Low** · confidence: **Medium** · effort: Low
- fix: mark the MR line as applying only where the Git section names a remote.
- closed: Closed 2026-09-15 in 929032a: the template now reads "MR, or the branch name where the repo has no remote".

### DOC-11 · The skill's description may fire on work that should stay in-session
- from: A3-11 · file: `~/.claude/skills/agy/SKILL.md:3`
- severity: **Low** · confidence: **Low** · effort: Low
- claim: two "when" clauses joined by "and" can read as alternatives, so "a repo-wide sweep" may
  trigger the skill even when the human never mentioned delegating.
- failure: a plain in-session sweep nudges toward a ~17k-token agy call nobody asked for.
- fix: rephrase as one conjunction with the delegation request as the precondition.
- closed: Closed 2026-09-15 on agent/audit-agy-fixes: the skill's description now fires only for an artifact task handed to it by the agy-driver subagent.

### DOC-12 · `agy-run.cmd` is documented as part of the wiring but is not allow-listed
- from: A3-3 · files: `~/.claude/settings.json:5`; `AGENTS.md:121`
- severity: **Low** · confidence: **High** · effort: Low
- fix: state that the `.cmd` shim is for humans typing by hand and is deliberately not
  allow-listed.
- closed: Closed 2026-09-15 in 929032a: AGENTS.md no longer presents agy-run.cmd as allow-listed wiring; it is a hand-typing shim that always prompts. No permission entry was added.

---

## ARC — architecture (Pass C, lead)

### ARC-1 · The premise the whole design rests on is half stale, and a safer supported configuration was never evaluated
- from: lead, verified against primary sources by a dedicated agent
- files: `AGENTS.md:184-186`; `~/.claude/skills/agy/SKILL.md:36-40`; `agy-run.py:20-24,157-158`
- severity: **High** · confidence: **High** for the flags, **Medium** for what replaces the blanket flag
- effort: Medium (needs empirical calls)
- evidence — the contract's statement of the premise:
```
agy always runs with tools auto-approved, because headless mode cannot prompt for a permission and
silently returns an empty answer instead.
```
- what is now established:
  - The **symptom is stale.** A denial is no longer silent. Google's headless documentation: "A
    tool that requires approval it cannot obtain is soft-denied: the run continues, exits `0`, and
    prints a notice to `stderr` naming the tool and how to allow it." Fixed in agy 1.1.3; a
    `denied_actions` field was added later. Installed build is 1.2.2. The stderr line observed
    during the build session was that notice — the wrapper reads the empty `response` but ignores
    the diagnosis sitting next to it.
  - **Issue #548 is open**, but its real title is "--print (headless) mode ignores
    permissions.allow entirely; 'persist to settings.json' approval option writes nothing", it has
    no maintainer reply, and community reports on 1.1.27 (Sept 2026) narrow it: `command()` grants
    in `~/.gemini/antigravity-cli/settings.json` are reportedly accepted and never consulted, while
    `read_file()` and `mcp()` grants in the same file are honoured.
  - **A documented middle ground exists and was never tried.** Google's modes documentation:
    "Tool permission rules configured via `/permissions` or `--dangerously-skip-permissions`
    continue to govern shell commands (`run_command`) across all execution modes", while
    `--mode accept-edits` runs "all standard file read, creation, and replacement operations"
    automatically. Headless support for `--mode` shipped in 1.1.12.
  - **`--sandbox` exists, works headlessly since 1.0.6, and is unused.** It constrains filesystem
    *and* network through native OS sandboxing (AppContainer on Windows), and blocks sensitive
    files: "Sensitive files like `~/.ssh` and `.env` are blocked."
  - **A deny list exists and is unused.** "Permissions are evaluated across three distinct access
    lists... `deny`, `ask`, and `allow`", precedence "Deny > Ask > Allow".
- claim: the project reached for the most permissive switch the CLI offers and built a git-based
  safety net under it, without evaluating the three narrower controls the same CLI ships. The
  contract's own rule — "Flags and model ids are checked against the tool, not remembered" — is the
  rule this violates.
- failure: every delegated call today runs with all tool permissions approved and no filesystem or
  network confinement, when a documented configuration exists that auto-approves edits, keeps shell
  commands gated, and blocks the credential files the contract protects only by policy.
- fix: test the supported configuration and move to whatever part of it works. Candidate:
  `--mode accept-edits --sandbox --add-dir <repo>` without `--dangerously-skip-permissions`.
  This needs real calls — see the plan.

### ARC-2 · `allowNonWorkspaceAccess: true` is a deliberate deviation from the vendor's safe default
- from: lead; reinforces SEC-1
- file: `~/.gemini/antigravity-cli/settings.json:2`
- severity: **High** · confidence: **High** · effort: Low
- evidence — Google's settings documentation:
```
Non-Workspace Access (allowNonWorkspaceAccess): Controls whether the agent can read or write files
outside your active project directories. Set to off by default for safety.
```
- claim: the setting is `true` on this machine. Combined with auto-approved tools it removes the
  only filesystem boundary agy has, which is what makes SEC-1 reachable in practice.
- fix: set it to `false`. Pass `--add-dir` when a call genuinely needs a second directory. This is
  the single cheapest risk reduction in the audit.

### ARC-3 · The rule protecting the OAuth session is policy, not mechanism
- from: lead
- files: `AGENTS.md:52-57`; `~/.gemini/antigravity-cli/settings.json:10-25`
- severity: **Medium** · confidence: **High** · effort: Low
- evidence:
```
5. **The Google session file is off limits.**
   Do not open, print, copy, or commit `~/.gemini/oauth_creds.json`, and do not build anything that
   reads it.
```
- claim: this is a well-written rule and it binds a cooperative agent. It binds nothing else. A
  deny entry, which agy supports and outranks allow, would make it a control. `--sandbox` would
  make it a control too.
- failure: the one asset whose loss the project was built to avoid is guarded by a sentence.
- fix: add a deny rule covering the credential paths, and prefer `--sandbox`, so the policy has a
  mechanism behind it.
- closed: Recorded 2026-09-15 as a known limit in AGY/README.md; not closable from the wrapper.

### ARC-4 · The audit directory blocks delegation
- from: lead
- files: `agy-run.py:78-85`; this audit's own output
- severity: **Low** · confidence: **High** · effort: Low
- claim: `./audit/` is untracked, so `git status --porcelain` is non-empty and `agy-run.py` refuses
  to start in this repository until it is committed or ignored.
- failure: the first delegation attempted after this audit fails with a refusal that looks like a
  bug in the wrapper.
- fix: commit `audit/`, or add it to `.gitignore` — but note SEC-4: ignoring it also makes it
  invisible to the guard.
