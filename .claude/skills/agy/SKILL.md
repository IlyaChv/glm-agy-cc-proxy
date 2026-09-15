---
name: agy
description: Delegate a large self-contained task to the Antigravity CLI (agy) on the Google AI Pro quota instead of doing it in this session. Use when the user asks to delegate or offload work to agy, Antigravity or Gemini, for a task big and self-contained enough to be worth ~17k tokens of Google quota - a repo-wide sweep, a long draft, reading an unfamiliar codebase, or work that suits one of agy's own skills. Not for single lookups or single edits.
---

# Delegating to agy

`agy` is Google's Antigravity CLI, signed in on the user's personal Google AI Pro account. It runs
as a separate agent with its own tools, context and skills. Claude Code stays the orchestrator:
it writes the brief, reads the result, and verifies it. `agy` is never the model behind Claude
Code - it is a worker called for one job at a time.

**agy produces artifacts; it never edits a project's working tree.** Its `--dir` is a side
directory prepared for the call - a fresh git repository in the session scratchpad with the inputs
copied in and committed - and what comes back is a path. Bringing the artifact into the project is
the lead's decision, made as an ordinary edit. Where a project carries `.claude/routing.json`,
the call is made by the `agy-driver` subagent, not by the lead session.

## The call

```bash
python C:/Users/cupik/.claude/bin/agy-run.py --dir <workdir> --prompt "<brief>"
```

Long brief: write it to a file first, then `--prompt-file <path>`. An inline `--prompt` over
24 000 characters makes no call at all - the wrapper exits with an error telling you to use
`--prompt-file` instead. The by-path fallback (a short "read this file" prompt, which costs agy an
extra read) only happens when the brief was already passed as `--prompt-file` and is over that
limit. Quote-heavy briefs should move to `--prompt-file` well before the limit.

| Flag | Use |
|---|---|
| `--dir` | working directory for agy; always pass it explicitly |
| `--prompt` / `--prompt-file` | the brief (mutually exclusive, one is required) |
| `--model` | default `gemini-3.8-flash-high`; `agy models` lists the rest (Gemini 3.1 Pro, Claude Sonnet/Opus 4.6, GPT-OSS 120B) |
| `--effort` | `low` / `medium` / `high` |
| `--agent` | one of agy's own agents: `Senior Developer`, `Technical Writer`, `UI Designer` |
| `--allow-shell` | let agy run terminal commands; needed for any shell work, and it removes every other boundary (see below) |
| `--no-tools` | pure-reasoning prompt: no sandbox, no accept-edits, no skip-permissions. Not a read-only switch |
| `--force` | skip the clean-tree check |
| `--timeout-min` | default 5 |
| `--no-sandbox` | do not pass `--sandbox` (it is on by default) |
| `--mode accept-edits\|plan` | agy's execution mode; defaults to `accept-edits` |
| `--add-dir` | additional workspace directory, repeatable; each must be a clean git repo too |

## What the default does, and why

The default is `--mode accept-edits --sandbox` with permissions enforced. Under it agy reads and
edits inside the workspace and **cannot write outside it**. Everything below was measured on
2026-09-13, not taken from documentation:

- default path: created and read files in the workspace, exited 0; a write to a path outside the
  workspace was **refused**;
- with `--allow-shell`: the same prompt wrote into a directory outside `--dir` that was not a git
  repository at all, with nothing to revert it;
- reads are **not** confined to the workspace on either path - agy read a file elsewhere on disk.
  Deny rules are what stop it, and they work: a denied path came back `DENIED` while an allowed
  file in the same call came through;
- agy's `command()` grants are ignored in headless mode, in both the plain and the `regex:` form.
  So there is no narrower way to give it a shell than `--allow-shell`;
- `read_file(*)` is the only read-grant form that matches at all. Path-scoped, bare-prefix and
  `regex:` forms were each tried and each failed, so the read grant cannot be narrowed - deny is
  the only working fence;
- `allowNonWorkspaceAccess` cannot be kept in agy's settings: agy rewrites that file and drops the
  value on every run. Do not rely on it.

**Use `--allow-shell` only when the task genuinely needs a terminal**, and say so to the user when
you do - it is the difference between "revertible inside one directory" and "wrote somewhere
nobody is tracking". If a default-path call comes back empty with a `command` permission named on
stderr, that is the signal the task needed a shell.

**Write the brief to prefer file tools.** Left to itself agy reaches for the shell even for
"create a file", which fails on the default path. Saying "use your file-writing tool, not a
terminal command" is usually the whole fix.

`--add-dir` exists but was not exercised.

Result: the answer on stdout, one `agy-run: status=... in=... out=...` line on stderr, exit code 0
only on success.

**Tools are on by default, and that is not really optional.** Headless mode cannot prompt for a
permission, so it auto-denies — and an auto-denied tool call comes back as `status=SUCCESS` with an
empty answer (antigravity-cli#548). The wrapper runs agy with `--dangerously-skip-permissions` so
that anything touching files works at all, and turns the empty answer into a non-zero exit so it
cannot pass for success. `--no-tools` is for prompts that need no file access whatsoever.

## What a call costs

Measured on this machine, not estimated:

- floor, any prompt at all: **~17 300 input tokens**. That is agy's own system prompt and built-in
  tools; a one-word question costs the same as a real one.
- reading one file and answering about it: **~30 000 input** plus ~28 500 cache-read, ~10 s.
- creating one trivial file: **~44 000 input** plus ~105 000 cache-read, ~40 s.
- a real multi-file code task: **~116 000 input, ~40 600 output, ~575 000 cache-read**, 139 s.
  Measured 2026-09-13 on a five-file, ~150-line Python project: add a second input format to the
  parser, a section to the report, and tests for both. Four files edited, nine tests to nineteen,
  all passing on the first attempt, default model, no shell. Roughly seven times the floor - that
  is the figure to judge a delegation against, not the trivial-file one above it.

Google AI Pro quota is measured in "compute effort" and refills every five hours. Two careless
write calls are a noticeable slice of it.

*Why this matters: the floor cost means delegation only pays when the task is genuinely large. A
question you could answer with one `grep` costs 17k tokens of someone's quota to ask.*

## When to delegate

- a research report that needs web search, delivered as a file;
- a long standalone document whose sections can be drafted without this session's context;
- a module or a fixture set generated from scratch into the side directory, to be reviewed and
  brought in by the lead;
- a task that matches one of agy's own skills, which Claude Code does not have;
- a sweep or audit over a copy of the inputs where only the written conclusion comes back.

## When not to

- one lookup, one file, one edit - cheaper and faster here;
- anything needing the context already loaded in this session (agy starts blank every call);
- a code change inside the project's working tree - that is the GLM worker's track (`glm-driver`),
  or an `implementer` subagent; agy's `--dir` never points at the project;
- verifying your own work. Delegation moves the work, never the responsibility for the result.

## Writing the brief

agy starts with no memory of this conversation. The brief carries everything:

- absolute paths, not "the file we were just looking at";
- the outcome wanted, phrased as an instruction ("rewrite", "list", "fix") - ask for suggestions
  and you get suggestions;
- explicit acceptance criteria;
- long material (logs, specs, excerpts) in a file that the brief points to, not pasted inline.

**Leave agy nothing to discover.** On the default path a brief that makes it look around fails, and
it costs a full call to find out. Asked to "read AGENTS.md in the current working directory" it
reached for a shell to locate the file and was denied; the identical task with the absolute path
plus "do not list the directory, do not search, do not run any terminal command" succeeded. So:
absolute paths for every file named, and say outright that no shell is needed. The same wording
prevents the silent no-op in Guard rails.

If `--dir` holds an `AGENTS.md`, agy reads it on its own - project rules do not need repeating.

## Delegating code work

The loop as measured on 2026-09-13. Each step is here because skipping it has a known failure:

1. **Commit first.** The wrapper refuses on a dirty tree, and that refusal is what makes the whole
   delegation revertible with `git checkout .`. In active development the tree is rarely clean, so a
   checkpoint commit is the standing cost of working this way - not something to route around with
   `--force`. Generated files (`__pycache__`, build output) dirty the tree too: gitignore them, and
   note that doing so also puts them outside the guard.
2. **Put the acceptance criteria in the brief** - the exact command that must pass, the public names
   that must keep working, what must not change - and say that you will run it and agy should not.
   Everything else follows "Writing the brief" above: absolute paths, nothing left to discover, no
   shell needed.
3. **Read the change report** the wrapper prints after the run. Nothing listed after a write task
   means the work did not happen, whatever the answer says.
4. **Run the project's own verification yourself** - tests, linter, type-checker. agy reporting
   success is not evidence: it answers from what it wrote, not from what runs. This is the step that
   turns a delegated diff into a result you can defend.
5. **Read the diff, then keep or revert.** Commit it, or `git checkout .` and re-brief.

Raise `--timeout-min` above the default 5 for multi-file work: the measured task took 139 s, and
that was a small project.

## Handling the result

- Report the usage line to the user when a call is expensive or when two run in a row. They are
  spending a quota that refills every five hours and cannot see it otherwise.
- **Do not retype a long answer into your reply.** What agy returned is already in your context once;
  typing it out again costs output tokens to produce and then rides along as input on every later
  turn. When the brief's deliverable is long - a draft, a report, a document - redirect stdout to a
  file in the session scratchpad (`> answer.md`; the wrapper forces UTF-8 on its own output, so
  non-ASCII survives the redirect), hand that file to the user (`SendUserFile`, or name the path), and
  keep your own message to the usage line plus two or three sentences. Read enough of it to verify the
  result - that responsibility never moves - but checking it is not reproducing it. A short answer
  stays inline: a verdict or a list costs less said than sent.
- Read what agy actually produced before believing the summary. Check `git diff` in `--dir`: it may
  have edited files even on a task phrased as a question. That is what the clean-tree requirement
  is for.
- Non-zero exit: read the reason before acting. On an empty answer the wrapper reads the permission
  name out of agy's own notice and says which one was denied and what to change - `command` means
  the task needs `--allow-shell`, `write_file` means the target is outside the workspace,
  `read_file` means a grant is missing or a deny rule blocked it, `escalate_admin` means a command
  tried to leave the sandbox. A timeout means a hung call instead. **Do not retry the same call
  unchanged** - act on what it named, reformulate, or do it in this session.

## Guard rails

agy edits files on any call where it can write, so the wrapper refuses to run unless `--dir` - and
every `--add-dir` - is a git repository with a clean working tree. That makes the outcome revertible
with `git checkout .`. Commit before delegating.

`--force` skips that check - only on an explicit request from the user, never to get past the
refusal on your own judgement.

`--dir` inside `.gemini`, `.claude`, `.ssh`, `.aws`, `.gnupg`, `.config`, `.docker`,
`AppData/Roaming` or `AppData/Local/Microsoft`, or set to the home directory itself, is refused
outright. `--force` does not lift that one. Setting `AGY_ALLOWED_ROOTS` (semicolon-separated)
narrows it further to just those roots.

Two things the wrapper now prints, and both are worth reading:

- **before the call**, the gitignored paths in each working directory. Those are outside the safety
  net - agy can change them and `git checkout .` will not bring them back;
- **after the call**, exactly which paths changed. Use it. agy has been observed answering "done."
  to a write task while creating nothing, with status SUCCESS and exit 0 - so *nothing changed*
  after a write task means the work did not happen, whatever the answer says. Giving absolute paths
  in the brief avoids the case that was reproduced.

Never read, print, or copy `~/.gemini/oauth_creds.json`. It is the live Google session; handling it
is how accounts get banned. Deny rules in agy's settings now cover that file and its neighbours,
and they were tested - but they are a fence around agy, not permission for you.
