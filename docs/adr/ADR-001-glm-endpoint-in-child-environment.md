# ADR-001 — The GLM endpoint is set in the child process's environment, never in `settings.json`

- **Status:** accepted
- **Date:** 2026-09-15
- **Owner:** @cupik
- **Affects:** `GLM/glm-run.py`, `GLM/switch-claude.ps1`, `~/.claude/settings.json`, the delegation path

## Context

Z.AI serves an Anthropic-compatible API, so Claude Code can be pointed at it by setting
`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` and the three `ANTHROPIC_DEFAULT_*_MODEL` names.
There are two places those can live, and the choice is not cosmetic.

`GLM/switch-claude.ps1` existed first and writes them into the `env` block of
`~/.claude/settings.json`. Three facts, all measured on 2026-09-14 and recorded in
`GLM/README.md`, make that a poor foundation for delegation:

- The desktop app reads `ANTHROPIC_DEFAULT_*_MODEL` from that file but **ignores**
  `ANTHROPIC_BASE_URL` for routing — it takes gateway routing from its own third-party inference
  configuration. The result is the worst combination available: the model names are swapped, the
  endpoint is not, and the session asks for a model it cannot reach.
- The observed failure is not a clean error. The Code tab kept reading files and stopped being able
  to run commands, reporting `glm-5.3[1m] is temporarily unavailable` on every operation needing a
  service-model call — in auto mode, the command-safety classifier, which lives in the haiku slot.
- Settings are read once at session start. Switching back does not repair a running session, and a
  session broken this way **cannot fix itself** by editing the file.

That third point is what settles it. A global file read once at startup is the wrong mechanism for
a per-call decision: its blast radius is every future session on the machine, and its effect on the
current one is nil.

## Decision

Delegation to GLM runs as a **child process** whose environment carries the Z.AI variables, and
`glm-run.py` never reads, writes or consults `~/.claude/settings.json`.

Specifically:

- `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` and the model names are set on the child's
  environment only, in `child_env()`. The key is read from `~/.claude/zai_api_key.txt` and is never
  an argument, because argv is readable by any process on this machine.
- The child is started with `--setting-sources project,local`, so it does not load the user
  settings file at all. This is what decouples the wrapper from the switcher: whichever mode the
  switcher last left that file in cannot change what a delegated call does.
- Inherited `ANTHROPIC_API_KEY` and other provider variables are dropped from the child's
  environment, so nothing of the user's Anthropic credentials is sent to a third party.

The switcher stays. It answers a different question — "run *this* session on GLM" — and the two are
no longer mutually exclusive.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Use the switcher for delegation: write `settings.json`, call, restore it | A crash between write and restore leaves the machine in GLM mode. Two sessions delegating at once race on one global file. And since settings are read at startup, the write does not even affect the caller — it buys nothing and risks everything. |
| Keep the switcher as the only GLM path | Changes every future session including the desktop app's, where it breaks command execution until switched back *and* restarted. Also cannot express "one task on GLM". |
| Put the Z.AI key in the `settings.json` `env` block permanently | The key sits in plaintext in a file that gets backed up and copied, and it applies to every project on the machine rather than to one call. |
| An Anthropic-API shim placing GLM under Claude Code as its model | Explicitly out of scope in `AGENTS.md`, and unnecessary: Z.AI is already Anthropic-compatible, so a child process reaches it directly. |

## Consequences

- **Accepted cost:** every call pays a fresh process's startup — ~18 000 tokens with tools, ~7 400
  with `--no-tools` (measured 2026-09-15). There is no session reuse, so a conversation with the
  worker is not possible; each call is one self-contained job. This is the same shape as `agy-run`
  and is a deliberate property, not an oversight.
- **Accepted cost:** the child does not inherit user-level settings, so the user's hooks and
  permission grants do not apply to the worker. Its safety comes from `glm-run.py`'s own guards —
  the clean-tree check, the forbidden-directory check, the subagent cap — and not from
  `settings.json`. Anything added to that file later will not fence the worker.
- **Known exposure:** the **project-level** `.claude/settings.json` *is* read, with its `env` block
  and its hooks. Inside this repo that is wanted; pointing `--dir` at an unfamiliar repository
  means executing that repository's settings.
- **Rollback cost:** small. Delete `GLM/glm-run.py`, the `glm` skill, the junction
  `~/.claude/skills/glm`, and the `Bash(python C:/Users/cupik/.claude/bin/glm-run.py:*)` entry in
  `~/.claude/settings.json`. Nothing else depends on it, and the switcher continues to work.
  *Amended 2026-09-15:* the entry was `Bash(python GLM/glm-run.py:*)` and the skill was
  project-scoped until that day; both went to an absolute path and a junction so the worker is
  reachable from every project. The decision above is unchanged by it.
  *Amended 2026-09-15 (2):* the repository moved to `Desktop/agent rules/glm-agy-cc-proxy`; the
  wrapper is now installed as a copy at `~/.claude/bin/glm-run.py` and the permission entry names
  that path. The decision is unchanged.
- **Follow-ups:** the auth-failure path — an absent, expired or revoked key, an exhausted quota, a
  Z.AI outage — has not been exercised; the wrapper's message for it is reasoned, not observed. It
  needs no second key to check: one call with a deliberately wrong token in a throwaway
  environment would settle it.
  *Closed 2026-09-15:* a large multi-file task was measured end to end — ~296 600 input-side
  tokens, 263 s, 14 tests to 33 passing on the first attempt. Figures in `GLM/README.md` and
  `.claude/routing.json`.

## Rules this creates for agents

Reach GLM only through `GLM/glm-run.py`; never set `ANTHROPIC_BASE_URL` or `ANTHROPIC_AUTH_TOKEN`
for a session in order to run a delegated call — a global file read once at startup cannot express
a per-call decision, and gets the desktop app's sessions as collateral.

Already recorded in `AGENTS.md` under "Every call to a worker goes through its wrapper", so it binds
every session without needing this file to be read.
