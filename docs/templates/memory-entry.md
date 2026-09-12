# Memory entry

<!--
Written after a repeated correction or an incident. One entry = one rule.
Keep the "Why" concrete — a rule without a real cost attached gets rationalised away.

Wording: say what to do, not only what to avoid ("Fetch the schema from /openapi.json before
writing types" beats "Never guess types"). Plain, specific language — no "ALWAYS", "NEVER",
"CRITICAL": current models over-trigger on shouted rules and start asking about everything.
-->

**Rule:** <one line, imperative, states the action to take>

**Why:** <the actual incident: what broke, how it was found, what it cost — hours, an outage, a
rollback, a customer.>

**How to apply:** <when this situation occurs, do exactly this. Include the command, the file, or
the check.>

**Example (optional):** <one real case, verbatim — the input that triggered it and the correct
response. Real material only; wrap in <example> tags if the entry is pasted into a prompt.>

**Scope:** <this repo | this subsystem | all projects>
**Added:** <YYYY-MM-DD> by <@name>

---

<!--
Promotion path:
  seen twice in one repo      → entry here
  seen in several repos       → a rule in AGENTS.md if every session needs it, otherwise a
                                path-scoped rule in .claude/rules/ (with the why either way)
  can be checked by a machine → a lint rule, a test, or a CI gate — and delete the entry

The last line matters: a rule that a machine can enforce should not be spending context budget in
a prompt file.
-->
