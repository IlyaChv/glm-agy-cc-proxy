# Audit progress — optimizator-max

Run started: 2026-09-13. Baseline commit: `f922159`. Working tree clean at start.

## Run configuration

| Parameter | Value | How it was decided |
|---|---|---|
| Mechanism | parallel subagents, **not** the Workflow tool | the human asked for subagents explicitly |
| Shard model / effort | `sonnet` (Sonnet 5), `high` | the human specified it; overrides the skill's per-role table |
| Business-critical module | `~/.claude/bin/agy-run.py` | the only executable artefact in the system |
| Out of scope | nothing | no area is being rewritten |
| Network for Pass B | not needed | no dependency manifest exists; the wrapper is Python stdlib only |
| Depth | thorough | requested |
| Report language | Russian | the whole project thread is Russian |

Not asked as questions: the answers above were determined by the repository, not by preference.
The one real decision is the Gate.

## Shape of the subject

7 tracked files, ~32 KB, all Markdown. One Python script (230 lines) and three config/skill files
live outside the repository and are audited as part of the system. No build, no test suite, no CI,
no dependency manifest.

## Passes

| Pass | Scope | Model | Status |
|---|---|---|---|
| Preflight | contract, index, mechanical sweep, skill deps | lead | done |
| A1 | `agy-run.py`, `agy-run.cmd` | sonnet / high | running |
| A2 | `AGENTS.md`, `CLAUDE.md`, `.claude/rules/*`, `docs/templates/*` | sonnet / high | running |
| A3 | `SKILL.md`, `~/.claude/settings.json`, agy settings, security posture | sonnet / high | running |
| B — dependencies | — | — | **not run: no manifest exists** |
| Verify | A3-1 refutation; the #548 premise against primary sources | sonnet | done |
| Phase 2 | §3.1–3.3 rendered one agent per section; §0–§2, §3.4, §4–§6 by the lead | sonnet / lead | done |
| Consolidation, Gate | — | lead | **at the Gate** |

## Preflight results

**Skill dependencies** — all seven present under `~/.claude/skills/`: `code-review`,
`codebase-design`, `research`, `request-refactor-plan`, `implement`, `tdd`, `wayfinder`.
No step runs skill-less.

**Mechanical sweep** — no `TODO`/`FIXME`/`HACK`/`@deprecated` anywhere in the repo or in
`agy-run.py`. No hardcoded-credential candidates. Angle-bracket placeholders appear in
`docs/templates/*` (correct — they are templates) and in the `paths:` frontmatter of
`.claude/rules/known-problems.md` (a live rule file; handed to A2 to confirm in context).

## Decisions taken

- Pass B skipped rather than faked: there is nothing to diff. Recorded as a coverage limit, not
  as a clean result.
- Pass C (structural) is not delegated. With three shards over eleven files the lead holds the
  whole subject already, and a fourth agent would re-read what consolidation is about to see.
- `./audit/` is untracked and therefore dirties the working tree, which makes `agy-run.py` refuse
  to start. Resolve before any delegation to agy: commit the audit directory or ignore it.

## Log

- Preflight complete, three shards launched.
- A3 back: 12 findings, 6 High — all six resting on one unverified assumption about how Claude
  Code matches `Bash(...:*)`. Sent to a verifier rather than passed through.
- A1 back: 12 findings, 3 High. A1-3 and A3-4 are the same defect found independently by two
  shards (the clean-tree guard is scoped to `--dir`, agy is not). Cross-lens agreement: confidence
  raised, severity unchanged.
- Lead read `agy --help` and `agy changelog` (both free, no API call). Found `--sandbox`,
  `--mode accept-edits|plan`, `--add-dir` — none used by the wrapper, none mentioned in the
  contract or the skill. Changelog entries mapped to versions: headless honoring `settings.json`
  `permissions` landed in **1.1.4**, `--mode` in headless in **1.1.12**, `--sandbox` in headless in
  **1.0.6**; installed build is **1.2.2**. This puts the project's founding premise in doubt.
  Sent to a second verifier with web access.
- A2 back: 7 findings. Two verified by the lead directly: the default branch is `master`, not the
  `main` the contract names, and `docs/adr/` does not exist.

## Phase 3 — execution (Gate passed)

The human approved all four groups at the Gate, including the quota-costing ARC-1 test.

Done by the lead, directly:

- **ARC-4** — `audit/` committed as `f51973e`; working tree clean, so delegation is unblocked.
- **ARC-2** — `allowNonWorkspaceAccess` set to `false` in
  `~/.gemini/antigravity-cli/settings.json`. Backup: `settings.json.bak-audit-2026-09-13`.

  **Correction, found by the review pass.** The sentence that stood here — "JSON re-parsed after
  the write; all six top-level keys preserved" — was false. The file on disk afterwards had five
  keys: `allowNonWorkspaceAccess` was *absent*, not `false`. The re-parse checked that the write
  produced valid JSON, not that the value survived, and the difference is the whole point of the
  change.

  **agy rewrites this file itself.** The evidence is `command(&)` coming back as
  `command(&)` — Go's `encoding/json` HTML escaping, which Python does not produce. A Go
  struct field with `omitempty` drops a `false` boolean, which fits exactly. So a `false` written
  here can be erased by the next agy run. Re-checked and set explicitly again after the
  experiment; **re-verify it after any future agy call** rather than assuming it holds.

Branch `agent/audit-contract-fixes` created off `f51973e`. Backups taken before delegating:
`agy-run.py.bak-audit-2026-09-13`, `SKILL.md.bak-audit-2026-09-13`.

Three implementation tracks running in parallel, no file overlap between them:

| Track | Files | Findings |
|---|---|---|
| A | `~/.claude/bin/agy-run.py` | COR-1…COR-8, SEC-1/SEC-4/DOC-5 docstring honesty, plus four new pass-through flags |
| B | `AGENTS.md`, `CLAUDE.md`, `.claude/rules/known-problems.md`, `docs/templates/*` | DOC-1, DOC-2, DOC-3, DOC-4, DOC-8, DOC-9, DOC-10, DOC-12 |
| C | `~/.claude/skills/agy/SKILL.md` | DOC-7, DOC-11, documentation of the new flags |

**Deferred deliberately.** DOC-6 (`trustedWorkspaces` points at agy's own bin directory) is coupled
to the ARC-1 result: now that `allowNonWorkspaceAccess` is `false`, what that list needs to contain
depends on how agy resolves its workspace in headless mode. Fixing it before the test would be a
guess. SEC-2 and ARC-3 (prune `permissions.allow`, add deny rules) are coupled the same way — while
`--dangerously-skip-permissions` is still the default path, neither list is consulted.

### ARC-1 experiment design

Three calls at most, in a throwaway git repo in the scratchpad — never in this project.

1. **Write-only task**, `--no-skip-permissions --mode accept-edits --sandbox`. Google documents
   `accept-edits` as auto-approving `write_to_file`. If this succeeds, a safer configuration exists
   for file work and the blanket flag is no longer needed for edits.
2. **Shell-command task**, same flags. This is the disputed one: community reports say `command()`
   grants in `~/.gemini/antigravity-cli/settings.json` are accepted and never consulted.
3. **Only if 1 fails** — repeat without `--sandbox`, to separate a sandbox failure from a
   permissions failure.

### Phase 3 results

| Track | Outcome | Commit |
|---|---|---|
| Lead: ARC-4, ARC-2 | audit committed, tree clean; `allowNonWorkspaceAccess` -> `false` | `f51973e` |
| B: eight contract fixes | 22 lines added, 27 removed; whole diff read by the lead before commit | `ee0da0d` |
| A: wrapper, ten items | diff read line by line; syntax, `--help` and the `--timeout-min 0` path re-verified by the lead | pending |
| C: skill, three items | diff read by the lead; later updated with the experiment result | pending |
| ARC-1 experiment | four calls, 128 658 input tokens; **safer configuration proven for file work** | pending |

**ARC-1 answered.** `--no-skip-permissions --mode accept-edits --sandbox`, with `read_file(*)` in
agy's `permissions.allow`, created a file and exited 0 — no `--dangerously-skip-permissions`. The
project's practical premise is disproven for file work. Shell work still needs the blanket flag:
under `--sandbox` a command leaving the sandbox asks for `escalate_admin`, which headless cannot
prompt for. Whether bare `command()` grants work without `--sandbox` remains untested; one more
call would answer it and was not spent.

`read_file(*)` was added to `~/.gemini/antigravity-cli/settings.json` during the experiment and
kept — the verified configuration depends on it. Backup of the original:
`settings.json.bak-audit-2026-09-13`.

**The wrapper's default was deliberately not changed.** The proven configuration does not cover
shell tasks, and switching the default without knowing how those behave would repeat the mistake
this audit found. That decision belongs to the human.

**Still open, deliberately.** DOC-6 (`trustedWorkspaces`), SEC-2 (prune `permissions.allow`),
ARC-3 (deny rules for credential paths). All three depend on whether the default moves to the
narrower path; deciding them now would be a guess. SEC-3 and SEC-5 were left as recorded risks.

### Review pass, and what it caught

An independent review of the whole change set ran on `opus` — a deliberate departure from the
human's "sonnet 5 high", because the writers were Sonnet agents and reviewing them with the same
class is a weaker check. Ten findings; the review was right on the ones that mattered.

| # | What it caught | Status |
|---|---|---|
| F1 | **`--no-tools --mode accept-edits` disabled the clean-tree guard while agy could still write** — the guard was gated on `--no-tools`, which now only withholds the blanket flag. Introduced by this change set. | fixed: the guard is gated on whether agy can write, and covers `--add-dir` too |
| F2 | `read_file(*)` grants read of every file, including the credential file rule 5 protects | partly: deny rules added for the credential paths, **their syntax is unverified** |
| F3 | The "verified" recipe ran under a settings state the machine no longer has | fixed: caveat added below and in `SKILL.md` |
| F4 | `allowNonWorkspaceAccess` was absent, not `false`; the record said otherwise | fixed, see above |
| F5 | A non-zero child exit only warned, so a crashed run still exited 0 | fixed: it now exits 1, printing the answer first |
| F6 | On timeout, `taskkill` failure was swallowed with no `proc.kill()` fallback | fixed: fallback added, failure reported |
| F7 | `json.loads("null")` succeeds, then `.get` raises — a traceback where the baseline gave a clean message | fixed: non-object payloads rejected with the diagnostic |
| F8 | `--add-dir` handed agy a directory the guard never inspected | fixed: each one is checked |
| F9 | `--no-tools`'s help and the docstring called it read-only, which it is not | fixed in both, and in `SKILL.md` |
| F10 | The file had been converted to CRLF, breaking the shebang and hiding the real diff | fixed: back to LF |

**F1 verified by running it.** Against a dirty repository, `--no-tools --mode accept-edits` and the
recommended recipe both now refuse before any call. Free to check — the refusal happens before agy
is launched.

**Caveat on the "verified" recipe (F3).** The four ARC-1 calls ran before the current settings
state. `allowNonWorkspaceAccess` is now explicitly `false` and `trustedWorkspaces` still lists only
agy's own bin directory (DOC-6, still deferred). Whether the recipe still succeeds against a
project directory under that combination has **not** been re-tested. Treat it as proven under the
conditions recorded in the report, not under today's.

### Quota actually spent

Six calls, not four. **~163 451 input tokens.**

The four ARC-1 calls were planned and approved: 21 101 + 34 913 + 54 426 + 18 218 = 128 658.

Two more, ~17 400 each, were **wasted by carelessness**: while checking the F1 fix across four flag
combinations, two of them correctly did not trigger the guard, so the placeholder prompt `x` went
through to a real call. A prompt guaranteed to fail before launch would have cost nothing. Recorded
rather than quietly folded into the total.

## Phase 4 — full verification battery (quota limit lifted by the human)

15 more calls, ~539 000 input tokens. Everything below is measured, not inferred.
Full table in `AUDIT_REPORT.md` section 6.

**Settled, and it changed the design:**

- The wrapper's **default is now `--mode accept-edits --sandbox` with permissions enforced.** Under
  it agy cannot write outside the workspace (T10). The old behaviour is now the explicit
  `--allow-shell`, which in the same test wrote to a non-git directory on the Desktop with nothing
  to revert (T11). `--no-skip-permissions` and the experimental `--sandbox` flag are gone: the
  first is the default, the second is on by default with `--no-sandbox` to turn it off.
- **`deny` rules work and outrank allow** (T2). Credential paths are enumerated in agy's settings,
  and that is now a mechanism behind AGENTS.md rule 5, not a policy line. ARC-3 closed.
- **`command()` grants are never consulted in headless**, plain or `regex:` (T4, T5). Shell work has
  no narrower path than `--allow-shell`. This settles the disputed half of ARC-1.
- **The read grant cannot be narrowed.** `read_file(*)` is the only form that matches; path-scoped,
  bare-prefix and `regex:` all fail (T3a/b/c). Reads are broad by necessity, fenced only by deny.
  SEC-2 resolved as far as it can be: the allow list is pruned to nine narrow `command()` entries
  plus `read_file(*)`, and the five invocation-mechanism entries are gone.
- **`allowNonWorkspaceAccess` cannot be persisted** (T7 reproduced it): agy rewrites its settings
  file and drops the boolean on every run. ARC-2's fix is not durable and the setting is not the
  boundary. Documented rather than fought.
- **`--add-dir` is a real spelling and the new guard covers it** (T6): a dirty additional directory
  is refused before any call.

**Corrections I had to make to my own earlier conclusions:**

- I reported T9 as "SEC-1 confirmed in the worst way" when agy wrote outside the workspace. That
  test was invalid - the target sat under `Temp`, which agy's sandbox documentation explicitly
  permits. T10 with a target outside temp was refused. Said so to the human immediately rather
  than letting the wrong conclusion stand.
- I previously left the default unchanged for lack of evidence about both branches. T10 and T11
  supplied it, so the decision was reversed on the evidence.

**DOC-6 (`trustedWorkspaces`) closed as a non-issue.** T1, T6, T7 and T12 all succeeded with it
still listing only agy's bin directory, so it gates nothing on the delegation path. Left alone
rather than changed on a guess about interactive sessions.

**Still not done, deliberately:** the `~/.gemini/config/config.json` route for `command()` grants.
It sits next to credential files and the branch it would unlock already has a working alternative.
A risk decision, not a quota one.

## Corrections to the record

- The hand-over summary of the build session said the three commits were on `main`. They are on
  `master`. `git symbolic-ref --short HEAD` → `master`, `init.defaultBranch` → `master`.
- The `Agent` tool accepts `model` but has **no** `effort` parameter. The shards therefore ran on
  Sonnet 5 at the session's inherited effort, not at the `high` that was asked for. Reported rather
  than papered over; it is also finding A2-3 against `CLAUDE.md`.

