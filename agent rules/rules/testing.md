---
paths:
  - "tests/**"
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/*_test.*"
  - "**/test_*.*"
---

# Editing tests

<!--
Deployed to .claude/rules/testing.md. Loaded when the agent opens a test file. Adjust `paths` to
the repo's test layout. The general testing rules (tests verify the solution, stubs, one test per
behaviour) stay in AGENTS.md because they bind implementation code too; what lives here applies
only when a test itself is being changed.
-->

| Purpose | Command |
|---|---|
| Single test by name | `<test-one "name">` |
| Whole suite | `<test>` |

- **Do not weaken a test to make it pass.** Loosening an assertion, adding a skip/xfail, widening a
  matcher, or replacing a real call with a mock in order to get green is a defect, not a fix. If the
  test is wrong, say so and stop.
  *Why: this converts a caught bug into an uncaught one and removes the signal that would have found
  it again.*
- **Changing an existing test is a separate commit** with the reason in the body: what the test used
  to guarantee, why that guarantee is wrong or has moved.
  *Why: it makes the one dangerous kind of diff visible in review instead of buried in a feature.*
- **Copy the structure of the closest existing test in this directory** for anything new here.
  *Why: a suite with three styles is a suite nobody maintains.*
