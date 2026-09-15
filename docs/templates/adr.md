<!--
Saved as docs/adr/ADR-0XX-<slug>.md. Status moves from "proposed" to "accepted" by the owner in
review, never by the agent that drafted it — an agent-accepted ADR is a decision nobody made.

Length: cover the substance and stop — no filler sections, no restating the decision in the
consequences.

Delete this comment block.
-->

# ADR-0XX — <decision in one line>

- **Status:** proposed | accepted | superseded by ADR-0YY
- **Date:** YYYY-MM-DD
- **Owner:** <@name>
- **Affects:** <modules / subsystems>

## Context

<What forced a decision. Constraints that were real at the time: load, team size, deadline,
existing systems, contracts we do not control.>

## Decision

<What we do. Present tense, specific enough to be checkable in code review.>

## Alternatives considered

| Option | Why rejected |
|---|---|
| `<...>` | `<...>` |

## Consequences

- Accepted cost: `<what this makes harder or slower>`
- Rollback cost: `<what it takes to undo this once it ships>`
- Follow-ups: `<what must be revisited and when>`

## Rules this creates for agents

<One or two lines that can be enforced during review, phrased as the action to take plus the why,
e.g. "Route all writes to X through Y — Y holds the idempotency key; a direct write duplicates
orders on retry." A rule that every task needs goes to AGENTS.md; one that only matters under
certain paths goes to .claude/rules/ with those paths; otherwise it lives only here and is found
only by whoever reads the ADR.>

<!--
Add a one-line row for this ADR to docs/adr/ADR-INDEX.md — the index is the only place the list of
decisions is maintained. Then delete this comment.
-->
