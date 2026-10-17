---
name: agy
description: How the workers:agy-driver subagent delegates one task to the Antigravity CLI (agy) on the Google AI Pro quota. Use when the agy-driver has been handed any request the user could make to the lead - web research, code changes in the project, a long document, work matching one of agy's own skills - in any directory, git or not. Not for in-session work and not for single lookups or single edits.
---

# Delegating to agy

`agy` is Google's Antigravity CLI, signed in on the user's personal Google AI Pro account. It runs
as a separate agent with its own tools, context and skills. Claude Code stays the orchestrator:
it writes the brief, reads the result, and verifies it. `agy` is never the model behind Claude
Code - it is a worker called for one job at a time.

**agy takes any request, exactly as the user would write it to the lead**, and may work directly
in the project directory, like GLM. Its `--dir` is whatever directory the task is about, git or
not, clean or not: a pre-call snapshot makes the change revertible. Which worker to use is a
matter of quota and availability (`workers:workers`). The call is made by the
`workers:agy-driver` subagent, not by the lead session.

**If a call fails with `Eligibility check failed: ... not currently available in your location`**
from a process the desktop app's agent started, it is the known incident of 2026-10-17
(`docs/incidents.md`): report it as an account/region error and stop; the lead reruns the same
command through the Terminal panel (`run_in_terminal`, output via `read_terminal`).

## The call

```bash
python "${CLAUDE_PLUGIN_ROOT}/AGY/agy-run.py" --dir <workdir> --prompt "<brief>"
```

Spell the command exactly like that; the path is filled in when this skill loads.

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
| `--model` | default `gemini-3.8-flash-high` (the wrapper's `DEFAULT_MODEL`); `agy models` for the current list, which now includes Claude models such as `claude-opus-5-5-medium` |
| `--effort` | `low` / `medium` / `high` |
| `--agent` | one of agy's own agents (`agy agents` lists them), e.g. `Senior Developer` |
| `--allow-shell` | let agy run terminal commands; needed for any shell work, not for web access, and it removes every other boundary (see below) |
| `--no-tools` | read-only reasoning call: `--mode plan` with the sandbox on, no accept-edits, no skip-permissions; skips the snapshot because nothing is written. Refused with `--allow-shell`, `--mode accept-edits` or `--no-sandbox` |
| `--force` | skip the pre-call snapshot: no revert, no change report |
| `--timeout-min` | default 5 |
| `--no-sandbox` | do not pass `--sandbox` (it is on by default) |
| `--mode accept-edits\|plan` | agy's execution mode; defaults to `accept-edits`. `--no-tools` always runs `plan`; with `--allow-shell` no `--mode` is passed unless set explicitly |
| `--add-dir` | additional workspace directory, repeatable; each is snapshotted too |

## What the default does, and why

The default is `--mode accept-edits --sandbox` with permissions enforced. Under it agy reads and
edits inside the workspace and **cannot write outside it**. Everything below was measured on
2026-09-13, not taken from documentation:

- default path: created and read files in the workspace, exited 0; a write to a path outside the
  workspace was **refused**;
- with `--allow-shell`: the same prompt wrote into a directory outside `--dir` that was not a git
  repository at all, with nothing to revert it - the snapshot covers `--dir` and `--add-dir` only;
- web: before every call the wrapper adds `read_url(*)` to `permissions.allow` in agy's settings
  (agy rewrites that file itself, hence every call). `search_web(*)` was tried and agy dropped it
  as unknown. So web research needs no `--allow-shell`;
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
you do, and never for web access - it is the difference between "revertible inside one
directory" and "wrote somewhere nobody is tracking". If a default-path call comes back empty with a `command` permission named on
stderr, that is the signal the task needed a shell.

**Write the brief to prefer file tools.** Left to itself agy reaches for the shell even for
"create a file", which fails on the default path. Saying "use your file-writing tool, not a
terminal command" is usually the whole fix.

`--add-dir` exists but was not exercised.

Result: the answer on stdout, one `agy-run: status=... in=... out=...` line on stderr (the model
is the one agy reports, else the one requested). Exit codes: **0** success; **1** agy failed or
reported an error; **2** refused before any call (bad arguments, forbidden directory, bad or
non-UTF-8 prompt file, missing binary, command line too long); **3** timeout.

**Tools are on by default, and that is not really optional.** Headless mode cannot prompt for a
permission, so it auto-denies — and an auto-denied tool call comes back as `status=SUCCESS` with an
empty answer (antigravity-cli#548). By default the wrapper runs agy with `--mode accept-edits
--sandbox`, permissions enforced — not skipped — so a tool call outside the workspace is refused
rather than silently denied; `--dangerously-skip-permissions` appears only when `--allow-shell` is
passed, because agy's `command()` grants are ignored in headless mode and that flag is the only way
to give it a shell. Either way the wrapper turns an empty answer into a non-zero exit so it cannot
pass for success. `--no-tools` is for prompts that must not write anything: it runs `--mode plan`
with the sandbox on, so agy can still read but not edit.

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
- a long document whose sections can be drafted without this session's context;
- a code change or a generated module, in the project directory or elsewhere;
- a task that matches one of agy's own skills, which Claude Code does not have;
- a sweep or audit where only the written conclusion comes back;
- any other request the user could make to the lead, when Google AI Pro is the quota to spend.

## When not to

- one lookup, one file, one edit - cheaper and faster here;
- anything needing the context already loaded in this session (agy starts blank every call);
- verifying your own work. Delegation moves the work, never the responsibility for the result.

## Writing the brief

agy starts with no memory of this conversation. The brief carries everything:

- absolute paths, not "the file we were just looking at";
- the outcome wanted, phrased as an instruction ("rewrite", "list", "fix") - ask for suggestions
  and you get suggestions;
- explicit acceptance criteria; the user's request as written is a fine core for the brief, with
  the context agy cannot know added around it;
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
directory without one leaves the sentences above as the only contract agy sees.

A brief for a research task, at the length it usually needs:

<example>
Write a report on how <library> handles retries, to
`C:/Users/HOME/AppData/Local/Temp/agy-E/retries.md`. Use your file-writing tool, not a terminal
command: do not list the directory, do not search, and do not run any shell command.

The material is `C:/Users/HOME/AppData/Local/Temp/agy-E/input/docs.md` and the library's own
documentation on the web. Sections: the default policy, how to change it, what it does on a
timeout, and what it does not retry.

Each factual claim carries its source URL and the sentence from that page, verbatim; close with a
section "not found / uncertain" for anything you could not source - a claim without a source is
listed there, not stated as fact.

If an input named here is missing or unreadable, or a criterion cannot be met, say so in your
answer as the first line, do what does not depend on it, and stop - do not substitute a guess.
</example>

## Delegating a write task

The loop, as measured. Each step is here because skipping it has a known failure:

1. **Nothing to prepare.** No git and no clean tree are needed: before the call the wrapper
   snapshots each `--dir` and `--add-dir` into a shadow git repository, so the call is revertible
   in any directory and the user's own uncommitted work is not in the way. Do not pass `--force`.
   Files the directory's `.gitignore` excludes are not in the snapshot.
2. **Put the acceptance criteria in the brief** - the exact command that must pass, the public names
   that must keep working, what must not change - and say that you will run it and agy should not.
   With no command, say what files must exist and what they must contain. Everything else follows
   "Writing the brief" above: absolute paths, nothing left to discover, no shell needed.
3. **Read the change report** the wrapper prints after the run: the changed paths against the
   snapshot, and a note if HEAD moved. Nothing listed after a write task means the work did not
   happen, whatever the answer says.
4. **Verify yourself** - the project's tests, linter, type-checker; with none, check that the
   produced files exist and are non-empty and spot-check them against the request. agy reporting
   success is not evidence: it answers from what it wrote, not from what runs.
5. **Keep or undo.** Keep: commit `wip(<scope>)` if the directory is a git repository that was
   clean before the call, otherwise leave the changes in place. Undo: run the command the wrapper
   printed (`git --git-dir="<snap>" --work-tree="<dir>" reset -q --hard HEAD && ... clean -fdq`),
   which reverts exactly agy's changes and leaves the user's own work as it was; then re-brief
   naming the failure. *Why not `git checkout .`: it would also discard the user's uncommitted
   work, and it cannot revert a non-git directory.*

Raise `--timeout-min` above the default 5 for multi-file work: the measured task took 139 s, and
that was a small project.

Run the wrapper with the Bash tool's `run_in_background` for anything that may exceed two minutes:
the Bash tool's own timeout (120 s default, 600 s max) kills the wrapper before the wrapper's own
limit (`--timeout-min` × 60 + 30 s) is reached, and the wrapper now takes agy down with it.

## Handling the result

- Put the usage line in your report to the lead when a call is expensive or when two run in a
  row, so the user, who is spending a quota that refills every five hours, can see it.
- **Do not retype a long answer into your reply.** What agy returned is already in your context once;
  typing it out again costs output tokens to produce and then rides along as input on every later
  turn. When the brief's deliverable is long - a draft, a report, a document - redirect stdout to a
  file in the session scratchpad (`> answer.md`; the wrapper forces UTF-8 on its own output, so
  non-ASCII survives the redirect), return that file's path in your report, and keep the
  report to the usage line plus two or three sentences. Read enough of it to verify the
  result - that responsibility never moves - but checking it is not reproducing it. A short answer
  stays inline: a verdict or a list costs less said than sent.
- Read what agy actually produced before believing the summary. Check the change report: it may
  have edited files even on a task phrased as a question. That is what the snapshot is for.
- Non-zero exit: read the reason before acting. On an empty answer the wrapper reads the permission
  name out of agy's own notice and says which one was denied and what to change - `command` means
  the task needs `--allow-shell`, `write_file` means the target is outside the workspace,
  `read_file` means a grant is missing or a deny rule blocked it, `escalate_admin` means a command
  tried to leave the sandbox. A timeout means a hung call instead. **Do not retry the same call
  unchanged** — and an account, eligibility, quota, auth or region error is reported at once and
  stops the task without any retry (the user fixes it by hand); otherwise act on what the
  wrapper's notice named, reformulate, or do it in this session.

## Guard rails

agy edits files on any call where it can write, so before such a call the wrapper snapshots
`--dir` and every `--add-dir` into a shadow git repository under
`%LOCALAPPDATA%\workers\snapshots` (kept 7 days). A tree over 20,000 files runs without a
snapshot and a warning says so. Git is not required and a dirty tree does not matter; the
snapshot is separate from the project's own history.

`--force` skips the snapshot - only on an explicit request from the user, never on your own
judgement.

`--dir` inside `.gemini`, `.claude`, `.ssh`, `.aws`, `.gnupg`, `.config`, `.docker`,
`AppData/Roaming` or `AppData/Local/Microsoft`, or set to the home directory itself, is refused
outright. `--force` does not lift that one. A `--prompt-file` under one of those same directories
is refused the same way, by `check_prompt_file_allowed`. Setting `AGY_ALLOWED_ROOTS`
(semicolon-separated) narrows it further to just those roots. `AGY_BIN` (absolute path to agy.exe)
pins the binary; a value that is not a file stops the call instead of falling back to another
build.

After the call the wrapper prints exactly which paths changed against the snapshot, and the
command that undoes them. Use it. agy has been observed answering "done." to a write task while
creating nothing, with status SUCCESS and exit 0 - so *nothing changed* after a write task means
the work did not happen, whatever the answer says. Giving absolute paths in the brief avoids the
case that was reproduced. Files the directory's `.gitignore` excludes are outside the snapshot:
agy can change them and the undo command will not bring them back.

Never read, print, or copy `~/.gemini/oauth_creds.json`. It is the live Google session; handling it
is how accounts get banned. Deny rules in agy's settings cover that file and its neighbours,
and they were tested - but they are a fence around agy, not permission for you.
