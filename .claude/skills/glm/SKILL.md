---
name: glm
description: Delegate a self-contained task to a GLM worker - Claude Code itself, running as a child process on the Z.AI endpoint - instead of doing it in this session. Use for execution work: a sweep across many files, implementing an approved plan, a mechanical pass, a long draft, or whenever the user asks to offload work to GLM or Z.AI. Available in every project; where a project carries a routing file, this is its default execution worker. Not for single lookups, single edits, or verifying your own work.
---

# Delegating to GLM

GLM is Claude Code itself, started as a child process pointed at the Z.AI endpoint. Unlike `agy`,
it is not a different agent with its own tools and habits - it is the same harness you are running
in, on a different model and a different quota. That has one large practical consequence: **it
reads this project's `CLAUDE.md` and `AGENTS.md` on its own**, so the brief does not have to
restate the contract.

This session stays the orchestrator: it writes the brief, reads the result, and verifies it. GLM
is never the model behind Claude Code - it is a worker called for one job at a time.

Which work goes to GLM rather than to agy or to a model here: `.claude/routing.json`, if the
project has one. Short version - GLM unless the job wants agy's own skills.

## The call

```bash
python C:/Users/cupik/Desktop/agy-cc-proxy/GLM/glm-run.py --dir <workdir> --prompt "<brief>"
```

**Spell the path exactly like that, from any directory.** The permission entry is
`Bash(python C:/Users/cupik/Desktop/agy-cc-proxy/GLM/glm-run.py:*)` and is matched against the
command text, not the file on disk: the absolute form runs unprompted from every project, while
`python GLM/glm-run.py` or `python glm-run.py` does not match and asks for confirmation.

The wrapper lives in the `agy-cc-proxy` repository and is called from there on purpose - that is
where its history is. This skill is the same file in both places: `~/.claude/skills/glm` is a
junction to `.claude/skills/glm/` in that repository, so edit it there, never through the
junction path.

Long brief: write it to a file and pass `--prompt-file <path>`. There is no length ceiling to work
around - the brief goes to the worker on stdin, not in the command line - so `--prompt-file` is
about keeping your own message readable, nothing more.

| Flag | Use |
|---|---|
| `--dir` | working directory for the worker; always pass it explicitly |
| `--prompt` / `--prompt-file` | the brief (mutually exclusive, one is required) |
| `--model` | leave unset for the GLM default (`glm-5.3[1m]`, the sonnet slot) |
| `--effort` | `low` / `medium` / `high` / `xhigh` / `max` |
| `--agent` | a custom agent for the child session |
| `--allow-shell` | let the worker run terminal commands; removes every boundary but the clean-tree guard |
| `--no-tools` | pure reasoning: `--tools ""`, no filesystem access at all. Skips the clean-tree check |
| `--force` | skip the clean-tree check. Does **not** skip the forbidden-directory check |
| `--timeout-min` | default 10 |
| `--mode` | `acceptEdits` (default) / `plan` / `dontAsk` / `manual` |
| `--add-dir` | additional workspace directory, repeatable; each must be a clean git repo too |

Result: the answer on stdout, a `glm-run: model=... in=... out=...` line on stderr, exit code 0
only on success.

## What the default does, and why

The default is `--permission-mode acceptEdits` with `--permission-prompts none`. Edits are
auto-approved; anything else that would need a human is **denied rather than queued**, so a call
fails fast instead of hanging on a prompt nobody can answer. Denied calls come back in the JSON
under `permission_denials`, and the wrapper prints them.

Everything below was measured on 2026-09-15, not taken from documentation:

- routing works: `modelUsage` reported `glm-5.3[1m]` with `contextWindow` 1000000, so the `[1m]`
  suffix and the paired autocompact window both take effect;
- the worker cannot fan out: subagent spawning is capped at depth 0 **and** the spawning tool is
  denied by name. Asked outright to delegate to a subagent, the worker answered `NO SUBAGENT`;
- MCP servers, skills and session files are off - `--strict-mcp-config` with no `--mcp-config`,
  `--disable-slash-commands`, `--no-session-persistence`;
- `~/.claude/settings.json` is **not** read by the worker (`--setting-sources project,local`), so
  whichever mode `GLM/switch-claude.ps1` last left that file in cannot change what a call does.
  Proved by controlled A/B: a project-level `env` var arrives with `project` in the source list and
  is `None` without it.

**The project-level `.claude/settings.json` *is* read**, with its `env` block and its hooks. Inside
this repo that is what you want. Pointing `--dir` at an unfamiliar repository means executing that
repository's settings - treat it the way you would treat running its build.

**`--allow-shell` is the real exception.** It passes `--dangerously-skip-permissions`, which
removes every boundary except the clean-tree guard - and that guard only covers git-tracked files
inside `--dir`. Use it only when the task genuinely needs a terminal, and say so to the user when
you do.

## What a call costs

Measured on this machine 2026-09-15, counting input plus cache-read, which is the number that
actually moves:

- `--no-tools`, any prompt at all: **~7 400 tokens**. That is the system prompt and nothing else.
- floor for a call **with tools**: **~17 800**. Tool definitions are most of the difference.
- creating one trivial file: **~35 800**, ~12 s.
- **a real multi-file task: ~296 600** (31 900 input + 264 800 cache-read), 17 500 output,
  23 turns, 263 s. A nine-file, 210-line Python package: add a second input format to the parser,
  a section to the report, and tests for both. Seven files edited, one added, 14 tests to 33, all
  passing on the first attempt with no repair turn and no shell.

**That last figure is the one to judge a delegation against** - roughly seventeen times the tools
floor - not the trivial-file number above it. Note the shape of the cost: input barely moves,
cache-read carries almost all of it, so a long task is not linear in the brief's length.

**`total_cost_usd` in the report is not a Z.AI charge.** Claude Code prices it from its own table,
which has no GLM entry - the JSON marks it `costBasis: "unknown"`. Compare calls by tokens; the
wrapper prints tokens first for that reason.

`[claude-code:unrecognized_model]` on stderr is cosmetic, from the same missing table entry. It
does not affect the result.

## When to delegate

- a sweep or audit across many files where only the conclusion comes back;
- implementing a plan that is already approved and written down;
- a mechanical pass: grep sweeps, manifest diffs, classification, extraction;
- a long draft whose sections need no context from this conversation;
- work that would otherwise fill this context window with files read once.

## When not to

- one lookup, one file, one edit - cheaper and faster here;
- anything needing the context already loaded in this session (the worker starts blank every call);
- a change with no mechanical way to check it. Verification is the safety net, and "the diff looks
  right" is not one;
- **verifying your own work, or GLM's.** Re-verification runs on `fable` or `opus`, never on
  whatever produced the thing. Delegation moves the work, never the responsibility for the result.

## Writing the brief

The worker starts with no memory of this conversation, so the brief carries everything:

- absolute paths, not "the file we were just looking at";
- the outcome wanted, phrased as an instruction ("rewrite", "list", "fix") - ask for suggestions
  and you get suggestions;
- explicit acceptance criteria, including the exact command that must pass;
- long material (logs, specs, excerpts) in a file the brief points to, not pasted inline.

What you do **not** need to restate: this project's rules. The worker is Claude Code, so it picks
up `CLAUDE.md` and `AGENTS.md` from `--dir` the same way you did. Repeating the contract in the
brief costs tokens and adds nothing.

## Delegating code work

1. **Commit first.** The wrapper refuses on a dirty tree, and that refusal is what makes the whole
   delegation revertible with `git checkout .`. In active development the tree is rarely clean, so
   a checkpoint commit is the standing cost of working this way - not something to route around
   with `--force`. Generated files dirty the tree too; `__pycache__/` is already gitignored here,
   and note that gitignoring something also puts it outside the guard.
2. **Put the acceptance criteria in the brief** - the exact command that must pass, the public
   names that must keep working, what must not change - and say that you will run it and the
   worker should not.
3. **Read the change report** the wrapper prints after the run. Nothing listed after a write task
   means the work did not happen, whatever the answer says.
4. **Run the project's own verification yourself.** The worker reporting success is not evidence:
   it answers from what it wrote, not from what runs.
5. **Read the diff, then keep or revert.** Commit it, or `git checkout .` and re-brief.

Raise `--timeout-min` above the default 10 for multi-file work.

## Handling the result

- **Do not retype a long answer into your reply.** What the worker returned is already in your
  context once; typing it out again costs output tokens and then rides along as input on every
  later turn. For a long deliverable, redirect stdout to a file in the session scratchpad
  (`> answer.md`; the wrapper forces UTF-8 on its own output, so non-ASCII survives the redirect),
  hand that file to the user, and keep your message to the cost line plus a few sentences. Read
  enough to verify it - that responsibility never moves - but checking is not reproducing.
- Report the cost line when a call is expensive or when two run in a row.
- Check `git diff` in `--dir` before believing the summary: the worker may have edited files even
  on a task phrased as a question. That is what the clean-tree requirement is for.

## Failure modes

Non-zero exit always means read the reason before acting. **Do not retry the same call unchanged.**

| What you see | What it means |
|---|---|
| `N tool call(s) were denied rather than prompted for` | the task needed a permission the default posture does not grant. If it genuinely needs a terminal, re-run with `--allow-shell`; otherwise narrow the brief |
| `the worker produced no output at all` | most likely an auth failure against the Z.AI endpoint. **This path has not been exercised** - the message is a reasoned guess, so read the stderr above it rather than trusting the wording |
| `did not return within Ns` | a stuck tool call, not a slow model - the worker's own request timeout is far longer. Narrow the task or raise `--timeout-min` deliberately |
| `exited N despite reporting success` | the child died after flushing output; the answer may be truncated. Treat the run as failed |
| `spawned N subagent(s) despite the depth cap` | the cap is not holding. Tell the user - this is a change in the tool, not a task problem |

## Guard rails

The worker edits files on any call where it can write, so the wrapper refuses to run unless
`--dir` - and every `--add-dir` - is a git repository with a clean working tree. That makes the
outcome revertible with `git checkout .`.

`--force` skips that check - only on an explicit request from the user, never to get past the
refusal on your own judgement.

`--dir` inside `.gemini`, `.claude`, `.ssh`, `.aws`, `.gnupg`, `.config`, `.docker`,
`AppData/Roaming` or `AppData/Local/Microsoft`, or set to the home directory itself, is refused
outright. `--force` does not lift that one, because the permission entry approves the program and
constrains no argument - this check is the floor under that. `GLM_ALLOWED_ROOTS`
(semicolon-separated) narrows it further.

Two things the wrapper prints, both worth reading: **before** the call, the gitignored paths in
each working directory, which are outside the safety net; **after** it, exactly which paths
changed.

The Z.AI key lives in `~/.claude/zai_api_key.txt` and reaches the worker through its environment.
Never pass it as an argument, never print it, never commit it - argv is readable by any process on
this machine.

Do not use the switcher next to the wrapper (`GLM/switch-claude.ps1` in `agy-cc-proxy`) to set
up a delegated call. It edits `~/.claude/settings.json`
and changes the endpoint for every future session, including the desktop app's, which then breaks
until it is switched back. The wrapper exists precisely so that one call does not do that.
