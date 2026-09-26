---
name: glm
description: Delegate a self-contained task to a GLM worker - Claude Code itself, running as a child process on the Z.AI endpoint - instead of doing it in this session. Use for execution work: a sweep across many files, implementing an approved plan, a mechanical pass, a long draft, or whenever the user asks to offload work to GLM or Z.AI. Available in every project; where a project carries a routing file, it is called from the `glm-driver` subagent, never from the lead session. Not for single lookups, single edits, or verifying your own work.
---

# Delegating to GLM

GLM is Claude Code itself, started as a child process pointed at the Z.AI endpoint. Unlike `agy`,
it is not a different agent with its own tools and habits - it is the same harness you are running
in, on a different model and a different quota. That has one large practical consequence: **it
reads this project's `CLAUDE.md` and `AGENTS.md` on its own**, so the brief does not have to
restate the contract.

This session stays the orchestrator: it writes the brief and reads the result. GLM is never the
model behind Claude Code - it is a worker called for one job at a time.

Which work goes to GLM rather than to agy or to a model here: `.claude/routing.json`, if the
project has one. Short version - GLM unless the job wants agy's own skills.

## The call

```bash
python C:/Users/cupik/.claude/bin/glm-run.py --dir <workdir> --prompt "<brief>"
```

**Spell the path exactly like that, from any directory.** The permission entry is
`Bash(python C:/Users/cupik/.claude/bin/glm-run.py:*)` and is matched against the
command text, not the file on disk: the absolute form runs unprompted from every project, while
`python GLM/glm-run.py` or `python glm-run.py` does not match and asks for confirmation.

The versioned source is `GLM/glm-run.py` in the `glm-agy-cc-proxy` repository - that is where its
history is. The call goes to the installed copy in `~/.claude/bin/`, so after editing the source,
copy it over the installed copy. This skill is the same file in both places: `~/.claude/skills/glm`
is a junction to `.claude/skills/glm/` in that repository, so edit it there, never through the
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
- work that would otherwise fill this context window with files read once;
- called by a `glm-driver`, not by the lead.

## When not to

- one lookup, one file, one edit - cheaper and faster here;
- anything needing the context already loaded in this session (the worker starts blank every call);
- a change with no mechanical way to check it. Verification is the safety net, and "the diff looks
  right" is not one;
- **verifying your own work, or GLM's.** Re-verification runs on `fable` or `claude-opus-5-5`, never on
  whatever produced the thing. Delegation moves the work, never the responsibility for the result.

## Writing the brief

The worker starts with no memory of this conversation, so the brief carries everything:

- absolute paths, not "the file we were just looking at";
- the outcome wanted, phrased as an instruction ("rewrite", "list", "fix") - ask for suggestions
  and you get suggestions;
- explicit acceptance criteria, including the exact command that must pass;
- long material (logs, specs, excerpts) in a file the brief points to, not pasted inline;
- the sentence: "If an input named here is missing or unreadable, or a criterion cannot be met, say
  so in your answer as the first line, do what does not depend on it, and stop - do not substitute
  a guess.";
- for a sweep or an audit: "every claim in the answer carries `path:line` and the matched text,
  verbatim; claims without one go under a final heading 'unsupported' rather than into the
  conclusion." That heading is what the driver counts, since a conclusion has no acceptance command;
- when the brief points at long material: "Before you start, quote the lines from <file> that the
  task depends on, verbatim, in a `<quotes>` block; if none apply, write 'No relevant quotes found'
  and stop. Use only that material and the files named here - where you need something not in them,
  say so instead of supplying it from memory."

What you do **not** need to restate: this project's rules. The worker is Claude Code, so it picks
up `CLAUDE.md` and `AGENTS.md` from `--dir` the same way you did. Repeating the contract in the
brief costs tokens and adds nothing.

A brief that has all of it, at the length it usually needs:

<example>
Rewrite the three loaders in `C:/src/app/io/` (`csv.py`, `jsonl.py`, `parquet.py`) so each one
takes an open binary stream instead of a path, and update every caller under `C:/src/app/`.
Keep the public function names as they are.

Acceptance: `python -m pytest tests/io -q` passes, and `rg -n "open\(" src/app/io` returns
nothing. I run both after your call - do not run them and do not claim they pass.

Do not touch: `C:/src/app/legacy/`, anything under `.claude/`, the lockfiles.

If an input named here is missing or unreadable, or a criterion cannot be met, say so in your
answer as the first line, do what does not depend on it, and stop - do not substitute a guess.
</example>

## Delegating code work

1. **Commit first.** The wrapper refuses on a dirty tree, and that refusal is what makes the whole
   delegation revertible with `git checkout .`. In active development the tree is rarely clean, so
   a checkpoint commit is the standing cost of working this way - not something to route around
   with `--force`. Generated files (`__pycache__`, build output) dirty the tree too: gitignore them,
   and note that doing so also puts them outside the guard.
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
  return that file's path in your report, and keep the report to the cost line plus a few sentences.
- Report the cost line when a call is expensive or when two run in a row.
- Check `git diff` in `--dir` before believing the summary: the worker may have edited files even
  on a task phrased as a question.

## Failure modes

Non-zero exit always means read the reason before acting: change the brief, change a flag, or do
the work in this session - a retry of the identical call usually reproduces the identical failure.
The exception is an account, eligibility, quota, auth or region error: report it at once, and
retry once to tell transient from blocked.

| What you see | What it means |
|---|---|
| `N tool call(s) were denied rather than prompted for` | the task needed a permission the default posture does not grant. If it genuinely needs a terminal, re-run with `--allow-shell`; otherwise narrow the brief |
| `the worker produced no output at all` | a stub `claude.exe` (`claude --version` fails) or a failure the payload never recorded; read the stderr above it rather than trusting the wording |
| `api_error_status=401` and `401 token expired or incorrect`, after ~5 minutes | an auth error: report it at once. With a valid key the known cause is the desktop app's `CLAUDE_CODE_ENTRYPOINT` reaching the child, which `child_env()` in `GLM/glm-run.py` drops; if it appears, check whether the installed copy in `~/.claude/bin` matches the source and say so rather than asking for a new key |
| `did not return within Ns` | a stuck tool call, not a slow model - the worker's own request timeout is far longer. Narrow the task or raise `--timeout-min` deliberately |
| `exited N despite reporting success` | the child died after flushing output; the answer may be truncated. Treat the run as failed |
| `spawned N subagent(s) despite the depth cap` | the cap is not holding. Tell the user - this is a change in the tool, not a task problem |
| denied Edit/Write on a path under `.claude/` (a skill or rule file in the project) | the default `acceptEdits` posture does not cover the project's own `.claude/` directory. Observed 2026-09-15. Make those edits from the driver after the call; do not re-brief the worker for them and do not reach for `--allow-shell` |

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

`GLM_CLAUDE_BIN` (absolute path to a `claude.exe`) makes the wrapper use that executable instead
of resolving the npm shim or falling back to the desktop app's copy; a value that is not a file is
ignored with a warning. Set it only when the resolution picks the wrong binary.

Two things the wrapper prints, both worth reading: **before** the call, the gitignored paths in
each working directory, which are outside the safety net; **after** it, exactly which paths
changed.

The Z.AI key lives in `~/.claude/zai_api_key.txt` and reaches the worker through its environment.
Never pass it as an argument, never print it, never commit it - argv is readable by any process on
this machine.

Do not use the switcher next to the wrapper (`GLM/switch-claude.ps1` in `glm-agy-cc-proxy`) to set
up a delegated call. It edits `~/.claude/settings.json`
and changes the endpoint for every future session, including the desktop app's, which then breaks
until it is switched back. The wrapper exists precisely so that one call does not do that.
