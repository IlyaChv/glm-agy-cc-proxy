@AGENTS.md

<!--
Claude Code reads CLAUDE.md, not AGENTS.md. The @-import above is what actually loads the
contract into context — a plain markdown link would not. Do not wrap it in backticks or move it
into a code block; import parsing skips those.

Alternative if you don't need Claude-specific additions:  ln -s AGENTS.md CLAUDE.md
(On Windows a symlink needs Administrator or Developer Mode — keep the import instead.)

Verify after setup: run /context and confirm CLAUDE.md appears under "Memory files".

Do not copy rules into this file. A second file with overlapping rules drifts within weeks, and
Claude may follow whichever it read first when two instructions conflict.
-->

## Claude Code specifics

<!--
Only harness-specific behaviour goes here; project rules stay in AGENTS.md. Each line is
"what + why", in the same calm wording. Delete the lines that do not apply to this repo.
-->

- **Progress text for the human.** Before the first tool call, say in a line what you are about
  to do. While working, a brief update when you find something important or change direction.
  Close with a recap that stands on its own: what was found, what was done, what is next.
  *Why: Fable 5.1 writes little between tool calls; without it a long run is a black box until it
  ends, and a wrong turn is caught an hour late.*
- **Batch independent tool calls.** First list privately what you need next, then request every
  item that does not depend on another's result in one response. Dependent calls run in order;
  no placeholder parameters.
  *Why: three sequential reads triple the wall-clock time for no information gain.*
- **Targeted edits, not whole-file rewrites.** When the end result is the same, edit the lines
  that change; rewrite a file only when it is short or most of it changes.
  *Why: a rewrite of a long file costs output tokens and time and hides the actual diff in review.*
- **Plan mode before changing anything under `~/.claude/`.** `settings.json`, `bin/agy-run.py`, and
  `skills/agy/SKILL.md` live outside this repository and outside its history.
  *Why: nothing here records that they changed, and a broken `settings.json` degrades every Claude
  Code session on this machine, not just this project.*
- **Write files with the Write and Edit tools, never with a shell heredoc.** `cat > file <<'EOF'`
  and PowerShell here-strings are not reliable here: the call fails with an unexpected-EOF parse
  error and leaves nothing written, and long content with quotes or apostrophes triggers it.
  *Why: the failure reads like a shell syntax problem, so the lost write is easy to miss and the
  retry costs the whole file again.*
- **Long documents are built in parts, never in one write.** Create the file with its first
  section, extend it with further edits; for anything report-sized, give each section to its own
  subagent writing its own file and assemble at the end. Never print a long document into the
  chat as well as writing it.
  *Why: one very long write can stall the turn or drop the connection, and everything in it is
  lost — including the reasoning that produced it.*
- **Scratch files go to the session scratchpad**, not into the repo.

## Models and subagents

**Delegate when any of these holds.** This is the default for such work, not an exception:

- the answer needs many files read but only a conclusion returned (a sweep, an audit, "where is
  this used", "does anything still call X");
- independent tracks that share no state — per module, per file, per dimension, per section;
- a long document whose sections can be drafted separately;
- a task you would otherwise read half the repository to finish.

**Do it yourself** for one lookup, one file, one edit, a step that needs the context you are
already holding, or verification of your own work.

*Why both directions: everything you read lands in this session's context and is re-sent on every
later turn, so twenty files read here keep costing for the rest of the run and crowd the window;
the same twenty read by a subagent are paid once and come back as a paragraph. In the other
direction, a subagent for a single grep is a round trip that returns a summary instead of the line
you needed.*

The observable sign that the triggers are not firing: this session has read more than a handful
of files for one question and no subagent has run yet. Delegate the next sweep instead of reading
it here.

Spawn subagents in the background and keep working on independent parts; wait only when the next
step needs their result. If one subagent can do the task, use one rather than several.

**How the model and effort reach a subagent.** Roles are agent types in `~/.claude/agents/` (or
`.claude/agents/` of the project, which overrides by name): one file per role, `model` and `effort`
in its frontmatter. Call the Agent tool with the role's `subagent_type`: it is the only way to set
effort for a plain subagent — the tool itself takes `model` but no effort; its `model`, when
given, overrides the definition's (that is how `verifier` runs on `opus` for findings written by
`fable`). Inside a Workflow script, `agent()` takes `model` and `effort` per call. Without either,
the subagent inherits this session's model and effort.

**Routing — which kind of work goes to which role, model or worker — lives in
`.claude/routing.json`, not here.** Read it before the first delegation of a session; it is also
the file to edit when the split should change, and the file to copy into a project that needs a
different one. Roles (`model-table-rev: 2026-09`): `glm-driver` (opus), `agy-driver` (sonnet),
`implementer` (sonnet), `sweeper` (sonnet), `drafter` (sonnet), `reviewer` (opus), `researcher`
(fable), `verifier` (fable; opus for fable's findings). The pairing and its why are in each role's
frontmatter and body.
*Why data rather than a table here: routing is a per-project decision, this file is a shared
contract. A table here gets quietly rewritten by whoever needs a different answer today, and the
change lands on every project at once.*

Two axes live in that file and are not interchangeable: a **subagent model** is picked from
`fable | opus | sonnet | haiku` and is started with the Agent tool; a **worker** (GLM, agy) is a
separate process reached through a wrapper in Bash, from a driver subagent. GLM has no subagent
form — `model: "glm"` matches nothing.

**Do not repoint the haiku slot.** It is not a role you assign; the harness calls it for its own
service work, including auto mode's command-safety classifier. When that slot points at a model
the session cannot reach, running commands stops working while file reads carry on.
*Why this is worth a paragraph: it does not present as a model problem. It looks like Bash is
broken, and the cause is one env var set earlier in a file that is read once at session start —
so the session that has it cannot fix itself by editing the file.*

Model aliases are the harness's (`fable`, `opus`, `sonnet`, `haiku`); full IDs if a tool requires
them: `claude-fable-5-1`, `claude-opus-5`, `claude-sonnet-5`. GLM is not an alias — it is
`glm-5.3[1m]`, reachable only through `glm-run.py`. Nothing below Sonnet-class: rechecking a
weaker model's routine output costs more than the routine.

Hard caps live outside the prompt: `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`,
`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` and `CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION` in the project
environment (present in the Claude Code binary from 2.1.270; not in the public docs, so re-check
with `grep -a` on the binary at each revision). Set them
as a ceiling, not as a target — a cap that blocks a normal fan-out does not save the work, it
moves it into this session where it is re-sent every turn.
*Why: a cap in the prompt is advisory; a cap in the environment holds when the model disagrees.*

<!--
Per-model notes (delete when not running that model):
- Opus 5 as lead: remove any "verify your work" / "double-check" / "use a subagent to verify"
  lines — it verifies on its own, and the instruction causes over-verification. Add
  "keep outputs reasonably concise" — effort does not shorten its visible replies.
  On delegation it can sit at either extreme, so tune to what you actually see: spawning agents
  for trivia means the damping above is too weak, while doing every sweep in-session means the
  triggers are not firing and any leftover "delegate sparingly" wording should go.
- Sonnet 5 as lead: it does not generalise an instruction from one item to the next; state scope
  ("apply this to every section"). Remove "summarise after every N tool calls" scaffolding.
- Fable 5.1 as lead: keep the progress-text line above; remove any "hold findings for the final
  response" line. Ask "are there any bugs in this program?" rather than "does it compile?" —
  the latter phrasing triggers safeguard false positives.
-->

## Delegating to workers

A worker is called from its driver (`glm-driver`, `agy-driver`), and the driver loads the worker's
skill — `glm` or `agy` — before the call, by convention, not an improvised `claude --print` or
`agy -p` in Bash. Nothing technical enforces this: the permission entry approves the wrapper
command itself whether or not the skill was loaded, and from any session.
*Why: the skill carries what a call costs, how a hung call behaves, and the loop for verifying a
delegated diff. Without it the first delegation is a guess made with someone's quota.*

Both skills are installed per machine, not per project: `~/.claude/skills/agy/` is a directory of
its own; `~/.claude/skills/glm` is a junction to `.claude/skills/glm/` in the `glm-agy-cc-proxy`
repository, so the skill has one source with history — edit it there, never through the junction.
The wrappers are `~/.claude/bin/agy-run.py` and `~/.claude/bin/glm-run.py`; the latter is an
installed copy of `glm-agy-cc-proxy/GLM/glm-run.py`, so after editing the source, copy it over.
Where a project has neither worker installed, delete the driver roles from `routing.json` rather
than leaving a route nobody can take.
