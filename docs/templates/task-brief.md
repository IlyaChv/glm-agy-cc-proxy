# Task brief — `<short title>`

<!--
Fill this in before starting an implementation session.
If the context was worked out in a design session, ask that session to write the handoff brief,
then review it yourself — pay attention to "Do not touch" and "Acceptance criteria". Those are the
two sections an agent gets wrong when writing its own brief.

Test before sending: show the brief to a colleague with no context on the task. If they would be
confused, the agent will be too. Say what to do, not only what to avoid; give the reason where a
rule looks arbitrary. Describe the outcome you need, not a step-by-step thinking procedure — the
model plans better than a hand-written plan.

Order matters: long material (specs, logs, contract excerpts) goes at the top, the task and the
criteria at the bottom. Quality drops when the question is buried above a wall of data.
-->

## Sources of truth — read in this order

1. `docs/adr/ADR-0XX.md`
2. `<spec / contract / openapi endpoint>`
3. `<code entry point>`

Product and architecture decisions in these documents are **settled**. Do not reopen them; if one
looks wrong, stop and say so.

<!-- Paste long excerpts here, each in its own tag, so the agent can tell material from instructions:
<documents>
  <document index="1">
    <source>error.log, <timestamp>, verbatim</source>
    <document_content>...verbatim...</document_content>
  </document>
</documents>
-->

## Task

<What to do. Use the live URL, the screenshot, the verbatim error text — not a paraphrase. Ask for
the action you want ("change", "implement", "migrate"), not for suggestions, or you will get
suggestions.>

Exact location: `<path/to/file>:<start>-<end>`
Hypothesis: `<where the cause almost certainly is>`

**Localise and prove the root cause before changing anything.** List the competing hypotheses,
quote the evidence that eliminates each, state the proof for the survivor (the failing input, the
log line, the query result), then fix.

*Why: a fix applied to a guessed cause silences the symptom and leaves the bug.*

## Expected result (optional, 1–3 real examples)

<!--
Examples steer format and structure better than descriptions. Use real material only — a response
copied from the live contract, an existing fixture, a current log line — never an invented one
(critical rule 4). Wrap each in <example> so it is not read as an instruction:
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
- Anything not required by the acceptance criteria above. No cleanup of surrounding code, no extra
  configurability, no comments or types added to code you did not change.

## Access

`<Narrow, explicit grant. Example: read-only production access for diagnosis; secrets come from CI
and are never read directly.>`

**Any write action, deployment, new dependency, or schema change: ask first.**

## State across sessions

- Progress notes: `<docs/progress/<task>.md>` — update before the context is compacted or the
  session ends; a fresh session starts by reading this file and `git log`.
- Structured status (if the task has many parts): `<tests.json / checklist file>`.

## Done means

- [ ] `<check command>` green locally
- [ ] Verified against reality: `<real data / live endpoint / browser / database / each role>`
- [ ] Non-goals respected — nothing extra in the diff, scratch files removed
- [ ] One MR, opened via `<mr command>`, or the branch name where the repo has no remote; commit
      body = what / why / how verified
- [ ] Before finishing, check each acceptance criterion above and say how it was verified

## Open questions

<Log blocking questions here and stop. Log non-blocking decisions here and continue.>
