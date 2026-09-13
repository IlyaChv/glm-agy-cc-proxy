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
orders on retry." If this ADR creates a rule that applies to every task, add it to AGENTS.md —
otherwise it lives only here and will be missed.>

---

*Add a one-line row for this ADR to `docs/adr/ADR-INDEX.md`, creating it if it does not exist yet.
The index is the only place the list of decisions is maintained.*
