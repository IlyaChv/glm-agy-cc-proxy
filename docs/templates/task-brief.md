# Task brief — `<short title>`

<!--
Fill this in before starting an implementation session.
If the context was worked out in a design session, ask that session to write the handoff brief,
then review it yourself — pay attention to "Do not touch" and "Acceptance criteria". Those are the
two sections an agent gets wrong when writing its own brief.

Test before sending: show the brief to a colleague with no context on the task. If they would be
confused, the agent will be too. Say what to do, not only what to avoid; give the reason where a
rule looks arbitrary. Describe the outcome you need, not a step-by-step thinking procedure — the
model plans better than a hand-written plan. Do not ask for the reasoning to be written out in the
reply either: effort sets how much the model thinks, and on Fable 5.1 and Opus 5.5 such a request can be
refused as `reasoning_extraction`.

Order matters: long material (specs, logs, contract excerpts) goes at the top, the task and the
criteria at the bottom. Quality drops when the question is buried above a wall of data.

Delete every comment block, including this one, once the brief is filled — the agent reads them
otherwise. Sections marked "for a defect" are deleted for a feature or migration task.
-->

## Sources of truth — read in this order

1. `<docs/adr/ADR-0XX-<slug>.md>`
2. `<spec / contract / openapi endpoint>`
3. `<code entry point>`

Decisions in these documents are settled (`AGENTS.md`, "Architecture decisions").

<!-- Long excerpts go right here, so the agent can tell material from instructions. Wrap each
verbatim excerpt in a <pasted_content> block whose opening and closing tags carry the same short
random id, a new id per block, each tag on its own line; the source goes on the line above it.
AGENTS.md rule 1 tells the agent what the block means. Fill the block below, or delete it if the task has no long material.

For a long excerpt, ask in the Task section for the relevant lines to be quoted back first (in
<quotes> tags) before the work starts. Ready to paste into the Task section: "Before you start,
quote the lines from <file> that the task depends on, verbatim, in a <quotes> block; if none
apply, write 'No relevant quotes found' and stop. Use only that material and the files named here
— where you need something not in them, say so instead of supplying it from memory." -->
Source: <error.log, <timestamp>, verbatim>
<pasted_content id="<4 random characters>">
<...verbatim...>
</pasted_content id="<the same id>">

## Task

<What to do. Use the live URL, the screenshot, the verbatim error text — not a paraphrase. Ask for
the action you want ("change", "implement", "migrate"), not for suggestions, or you will get
suggestions. If you want more than the minimum — extra features, interactions, a fully worked
implementation — say so in this section; it is not inferred from a short task line. Give the
complete specification here rather than adding it turn by turn.>

For a defect (delete for a feature or migration):

- Exact location: `<path/to/file>:<start>-<end>`
- Hypothesis: `<where the cause almost certainly is>`
- **Prove the root cause before changing anything, and say what proves it** — the failing input,
  the log line, or the query result.
  *Why: a fix applied to a guessed cause silences the symptom and leaves the bug.*

## Expected result (optional, 1–3 real examples)

<!--
Examples steer format and structure better than descriptions. Use real material only — a response
copied from the live contract, an existing fixture, a current log line — never an invented one
(AGENTS.md rule 4). Wrap each in <example> so it is not read as an instruction:
<examples>
  <example>
    <input>GET /v1/orders/42</input>
    <output>{...copied from the live endpoint...}</output>
  </example>
</examples>
-->

## Acceptance criteria

1. `<checkable statement — someone else can verify this without asking you>`
2. `<...>`

## Do not touch (non-goals)

- `<explicitly out of scope>`
- `<e.g. "document only, no code" / "deployment only, do not rewrite the feature">`
- Anything not required by the acceptance criteria above (the Scope rule in `AGENTS.md`).

## Access

`<What this task may reach beyond the repo, narrowly. Example: read-only production access for
diagnosis. Name the system and the level — never a credential; those come from CI or the vault.>`

Shared-system writes, deployments, new dependencies, schema changes: prepare, then ask
(`AGENTS.md`, rule 2 and the dependency rule under "Development rules").

## State across sessions

- Progress notes: `docs/progress.md` — update before the context is compacted or the
  session ends; a fresh session starts by reading this file and `git log`.
- Structured status (if the task has many parts): `<tests.json / checklist file>`.

## Done means

The Definition of done in `AGENTS.md` applies in full. On top of it, for this task:

- [ ] Reality check specific to this task: `<the exact endpoint, dataset, screen, or role to verify
      against — the DoD names the kind, this names the instance>`
- [ ] Every acceptance criterion above checked, with how it was verified stated
- [ ] `<anything this task needs that the Definition of done does not cover>`

## Open questions

<Log blocking questions here and stop. Log non-blocking decisions here and continue.>
