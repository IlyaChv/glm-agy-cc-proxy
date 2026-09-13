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

Model and effort by role (revised 2026-09; names change, roles do not — see the playbook):

| Role | Model | Effort | Why this pairing |
|---|---|---|---|
| Lead: design, plans, briefs, consolidation, final review | `fable` (Fable 5.1) | `high`; `xhigh` only where measured | Strongest reasoning. At `xhigh`/`max` it drafts long deliverables twice (in thinking, then in the reply) — keep reports and briefs at `high`. |
| Implementation of an approved plan | `sonnet` (Sonnet 5) | `high`; `xhigh` for hard multi-file work | Follows the plan literally and precisely. At `low`/`medium` it scopes narrowly and can under-think — raise effort, do not prompt around it. |
| Code review, line-level finding shards | `opus` (Opus 5) | `medium` fast pass; `high` thorough | Review precision and recall hold at lower effort. Ask it to report everything with confidence and severity; filter in a separate step — "only high-severity" makes it under-report. |
| Mechanical: grep sweeps, manifest diffs, classification, extraction | `sonnet` (Sonnet 5) | `low`/`medium` | Strict effort scoping is a feature here. Evaluate `fable` at `low` as a replacement: often cheaper per task while scoring higher. |
| Research with search or retrieval | `fable` (Fable 5.1) | `medium`/`high`, not `low` | At `low` Fable 5.1 answers from memory instead of searching. |
| Adversarial verifier of another agent's findings | `fable` (Fable 5.1) | `high` | Writer and verifier are different agents, ideally different models. |
| Drafting one section of a long deliverable | `sonnet` (Sonnet 5) | `medium` | Rendering settled material into a section is mechanical; parallel sections keep any single write short. |

Model aliases are the harness's (`fable`, `opus`, `sonnet`); full IDs if a tool requires them:
`claude-fable-5-1`, `claude-opus-5`, `claude-sonnet-5`. Nothing below Sonnet-class: rechecking a
weaker model's routine output costs more than the routine.

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
- Sonnet 5 as lead: it does not generalise an instruction from one item to the next; state scope
  ("apply this to every section"). Remove "summarise after every N tool calls" scaffolding.
- Fable 5.1 as lead: keep the progress-text line above; remove any "hold findings for the final
  response" line. Ask "are there any bugs in this program?" rather than "does it compile?" —
  the latter phrasing triggers safeguard false positives.
-->
