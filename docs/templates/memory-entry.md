---
name: <short-kebab-case-slug>
description: <one line — what this rule prevents; the index reads it to decide relevance>
metadata:
  type: feedback | project | reference | user
  scope: this repo | this subsystem | all projects
  added: <YYYY-MM-DD> by <@name, or "agent session" when the agent writes it>
---

<!--
Written after a repeated correction or an incident. One entry = one rule, so that an entry can be
promoted or deleted on its own — a file holding three rules is never deleted because one still
applies.

Keep the "Why" concrete — a rule without a real cost attached gets rationalised away.

Wording: say what to do, not only what to avoid ("Fetch the schema from /openapi.json before
writing types" beats "Never guess types"). Plain, specific language — no "ALWAYS", "NEVER",
"CRITICAL": current models over-trigger on shouted rules and start asking about everything.

The frontmatter is the shape Claude Code's auto-memory uses, so the same file works in the repo's
`docs/memory/` (with its `MEMORY.md` index, created at install) and in the agent's own memory
directory.

Length: cover the substance and stop — no filler sections, no restating the rule in "How to
apply".

Delete this comment block.
-->

**Rule:** <one line, imperative, states the action to take>

**Why:** <the actual incident: what broke, how it was found, what it cost — hours, an outage, a
rollback, a customer.>

**How to apply:** <when this situation occurs, do exactly this. Include the command, the file, or
the check.>

**Example (optional):** <one real case, verbatim — the input that triggered it and the correct
response. Real material only; wrap in <example> tags if the entry is pasted into a prompt.>

Related: [[<name of a related entry, if any>]]

---

<!--
After writing the file, add one line to the index `MEMORY.md` next to it:
  - [<Title>](<file>.md) — <one-phrase hook>
The index is what gets loaded; an entry without an index line is never found.

Promotion path:
  seen twice in one repo      → entry here
  seen in several repos       → a rule in AGENTS.md if every session needs it, otherwise a
                                path-scoped rule in .claude/rules/ (with the why either way)
  can be checked by a machine → a lint rule, a test, or a CI gate — and delete the entry

The last line matters: a rule that a machine can enforce should not be spending context budget in
a prompt file.
-->
