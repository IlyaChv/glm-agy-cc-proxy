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
- **Delegation to `agy` runs through the `agy` skill, by convention** — not an improvised `agy -p`
  in Bash. Nothing technical enforces this; the permission entry approves the wrapper command
  itself whether or not the skill was loaded.
  *Why: the skill carries what a call costs and how a hung call behaves; without it the first
  delegation is a guess made with someone's quota.*
- **Delegation to GLM runs through the `glm` skill**, in `.claude/skills/glm/` — a project skill,
  not a user-level one, because `glm-run.py` is reached by a repo-relative path and its permission
  entry is written the same way. `GLM/README.md` holds the measurements behind it.
  *Why it is scoped to this project: a user-level skill would point at `GLM/glm-run.py` in every
  other repository too, where that path is nothing.*
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

Delegation criteria and the reasoning behind them live in `AGENTS.md`, "Delegate sweeps and
independent tracks; do single lookups yourself" — this section adds only what is specific to
Claude Code.

**If tokens are burning fast and everything is happening in this session, the triggers in
`AGENTS.md` are not firing — delegate the next sweep instead of reading it here.**

Spawn subagents in the background and keep working on independent parts; wait only when the next
step needs their result. If one subagent can do the task, use one rather than several. Pass the
model per call from the table below; without it the subagent inherits this session's. Effort is not
currently settable per subagent call — the Effort column is the pairing to use once it becomes
controllable, and applies today to work done directly in this session.

**Routing — which kind of work goes to which model or worker — lives in `.claude/routing.json`,
not here.** Read it before the first delegation of a session. It is also the file to edit when the
split should change, and the file to copy into another project that needs a different one.
*Why it is data rather than a table in this file: routing is a per-project decision, while this
file is a shared contract. A table here gets quietly rewritten by whoever needs a different answer
today, and the change lands on every project at once.*

Two axes live in there, and they are not interchangeable: a **subagent model** is picked from
`fable | opus | sonnet | haiku`, while **a worker** is a separate process reached through a wrapper
in Bash. GLM has no subagent form — `model: "glm"` matches nothing.

**Do not repoint the haiku slot.** It is not a role you assign; the harness calls it for its own
service work, including auto mode's command-safety classifier. Measured in this session on
2026-09-15: with `ANTHROPIC_DEFAULT_HAIKU_MODEL` set to a GLM id, a child process's stderr carried
`{"model":"glm-5.3-flash[1m]","query_source":"agent_classifier"}`. When that slot points at a
model the session cannot reach, running commands stops working while file reads carry on.
*Why this one is worth a paragraph: it does not present as a model problem. It looks like Bash is
broken, and the cause is one env var set earlier in a file that is read once at session start —
so the session that has it cannot fix itself by editing the file.*

Effort is not settable per subagent call today; it applies to work done directly in this session.
Use `high` for lead work and re-verification, and raise it rather than re-prompt when the output
comes back thin.

Model aliases are the harness's (`fable`, `opus`, `sonnet`, `haiku`); full IDs if a tool requires
them: `claude-fable-5-1`, `claude-opus-5`, `claude-sonnet-5`. GLM is not an alias here at all — it
is `glm-5.3[1m]`, reachable only through `glm-run.py`.

Hard caps live outside the prompt: `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` and
`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (Claude Code 2.1.217+) in the project environment. Set them
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
- Fable 5.1 as lead: keep the progress-text line above; remove any "hold findings for the final
  response" line. Ask "are there any bugs in this program?" rather than "does it compile?" —
  the latter phrasing triggers safeguard false positives.
-->
