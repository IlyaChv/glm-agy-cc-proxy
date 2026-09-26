---
name: agy
description: How the agy-driver subagent delegates one artifact task to the Antigravity CLI (agy) on the Google AI Pro quota. Use when the agy-driver has been handed a task whose deliverable is a file or folder produced from scratch in a side directory - a research report with web search, a long standalone document, a generated module, or work matching one of agy's own skills - and the result comes back as a path. Not for in-session work, not for editing this project's working tree, and not for single lookups or single edits; ordinary execution that ends in a commit goes to the GLM worker instead.
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

Long brief: write it to a file first, then `--prompt-file <path>`. What the wrapper measures is the
**quoted command line** (`subprocess.list2cmdline`) against 32 767 - 512 chars, not the brief's raw
length - Windows argv quoting expands embedded quotes and backslashes, so a quote-heavy brief
overflows well before its character count suggests. Over that limit with an inline `--prompt`, the
call is never made: the wrapper exits with an error naming the quoted length and telling you to use
`--prompt-file`. **An inline brief is never auto-converted to a file.** The by-path fallback (a
short "read this file" prompt, which costs agy an extra read) happens only when the brief was
already passed as `--prompt-file`.

| Flag | Use |
|---|---|
| `--dir` | working directory for agy; always pass it explicitly |
| `--prompt` / `--prompt-file` | the brief (mutually exclusive, one is required) |
| `--model` | default `gemini-3.8-flash-high` (the wrapper's `DEFAULT_MODEL`); `agy models` for the current list |
| `--effort` | `low` / `medium` / `high` |
| `--agent` | one of agy's own agents: `Senior Developer`, `Technical Writer`, `UI Designer` |
| `--allow-shell` | let agy run terminal commands; needed for any shell work, and it removes every other boundary (see below) |
| `--no-tools` | pure-reasoning prompt: no sandbox, no accept-edits, no skip-permissions. Not a read-only switch |
| `--force` | skip the clean-tree check |
| `--timeout-min` | default 5 |
| `--no-sandbox` | do not pass `--sandbox` (it is on by default) |
| `--mode accept-edits\|plan` | agy's execution mode; defaults to `accept-edits` unless `--no-tools` or `--allow-shell` is given, in which case no `--mode` is passed unless set explicitly |
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
empty answer (antigravity-cli#548). By default the wrapper runs agy with `--mode accept-edits
--sandbox`, permissions enforced — not skipped — so a tool call outside the workspace is refused
rather than silently denied; `--dangerously-skip-permissions` appears only when `--allow-shell` is
passed, because agy's `command()` grants are ignored in headless mode and that flag is the only way
to give it a shell. Either way the wrapper turns an empty answer into a non-zero exit so it cannot
pass for success. `--no-tools` is for prompts that need no file access whatsoever.

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
- long material (logs, specs, excerpts) in a file that the brief points to, not pasted inline;
- the sentence: "If an input named here is missing or unreadable, or a criterion cannot be met, say
  so in your answer as the first line, do what does not depend on it, and stop - do not substitute
  a guess.";
- for a research deliverable: "each factual claim carries its source URL and the sentence from that
  page, verbatim, and the report closes with a section 'not found / uncertain' - a claim you could
  not source is listed there, not stated as fact.";
- when the brief points at long material: "Before you start, quote the lines from <file> that the
  task depends on, verbatim, in a `<quotes>` block; if none apply, write 'No relevant quotes found'
  and stop. Use only that material and the files named here - where you need something not in them,
  say so instead of supplying it from memory."

The brief travels in argv and is visible in the process list to any process on this machine while
the call runs, whether passed inline or via `--prompt-file`; nothing secret goes into a brief.

**Leave agy nothing to discover:** absolute paths for every file named, and say outright that no
shell is needed ("do not list the directory, do not search, do not run any terminal command").
*Why:* on the default path a brief that makes agy look around fails and costs a full call to find
out — a relative "read AGENTS.md in the current working directory" reaches for a shell and is
denied, while the same task with the absolute path and that sentence succeeds. The same wording
prevents the silent no-op in Guard rails.

If `--dir` holds an `AGENTS.md`, agy reads it on its own - project rules do not need repeating. A
side directory usually holds none, so the sentences above are the only contract agy sees there.

A brief for an artifact task, at the length it usually needs:

<example>
Write a report on how <library> handles retries, to
`C:/Users/cupik/AppData/Local/Temp/agy-E/retries.md`. Use your file-writing tool, not a terminal
command: do not list the directory, do not search, and do not run any shell command.

The material is `C:/Users/cupik/AppData/Local/Temp/agy-E/input/docs.md` and the library's own
documentation on the web. Sections: the default policy, how to change it, what it does on a
timeout, and what it does not retry.

Each factual claim carries its source URL and the sentence from that page, verbatim; close with a
section "not found / uncertain" for anything you could not source - a claim without a source is
listed there, not stated as fact.

If an input named here is missing or unreadable, or a criterion cannot be met, say so in your
answer as the first line, do what does not depend on it, and stop - do not substitute a guess.
</example>

## Delegating a code artifact (in the side directory)

The loop, as measured. It runs in the side directory the driver prepared (see "agy never edits a
project's working tree" above); bringing the result into the project is a separate edit by the
lead. Each step is here because skipping it has a known failure:

1. **Commit the inputs first.** The wrapper refuses on a dirty tree, and that refusal is what makes
   the call revertible with `git checkout .` in the side directory - not something to route around
   with `--force`. Generated files (`__pycache__`, build output) dirty the tree too: gitignore them,
   and note that doing so also puts them outside the guard.
2. **Put the acceptance criteria in the brief** - the exact command that must pass, the public names
   that must keep working, what must not change - and say that you will run it and agy should not.
   Everything else follows "Writing the brief" above: absolute paths, nothing left to discover, no
   shell needed.
3. **Read the change report** the wrapper prints after the run. Nothing listed after a write task
   means the work did not happen, whatever the answer says.
4. **Run the verification yourself, in the side directory** - tests, linter, type-checker. agy reporting
   success is not evidence: it answers from what it wrote, not from what runs. This is the step that
   turns a delegated diff into a result you can defend.
5. **Read the diff, then keep or revert.** Commit it in the side directory and return the path, or
   `git checkout .` and re-brief.

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
  unchanged** — except an account, eligibility, quota, auth or region error, which is reported at
  once and retried once to tell transient from blocked; otherwise act on what it named,
  reformulate, or do it in this session.

## Guard rails

agy edits files on any call where it can write, so the wrapper refuses to run unless `--dir` - and
every `--add-dir` - is a git repository with a clean working tree. That makes the outcome revertible
with `git checkout .`. Commit before delegating.

`--force` skips that check - only on an explicit request from the user, never to get past the
refusal on your own judgement.

`--dir` inside `.gemini`, `.claude`, `.ssh`, `.aws`, `.gnupg`, `.config`, `.docker`,
`AppData/Roaming` or `AppData/Local/Microsoft`, or set to the home directory itself, is refused
outright. `--force` does not lift that one. A `--prompt-file` under one of those same directories
is refused the same way, by `check_prompt_file_allowed`. Setting `AGY_ALLOWED_ROOTS`
(semicolon-separated) narrows it further to just those roots. `AGY_BIN` (absolute path to agy.exe)
pins the binary; a value that is not a file stops the call instead of falling back to another
build.

Two things the wrapper prints, and both are worth reading:

- **before the call**, the gitignored paths in each working directory. Those are outside the safety
  net - agy can change them and `git checkout .` will not bring them back;
- **after the call**, exactly which paths changed. Use it. agy has been observed answering "done."
  to a write task while creating nothing, with status SUCCESS and exit 0 - so *nothing changed*
  after a write task means the work did not happen, whatever the answer says. Giving absolute paths
  in the brief avoids the case that was reproduced.

Never read, print, or copy `~/.gemini/oauth_creds.json`. It is the live Google session; handling it
is how accounts get banned. Deny rules in agy's settings cover that file and its neighbours,
and they were tested - but they are a fence around agy, not permission for you.
