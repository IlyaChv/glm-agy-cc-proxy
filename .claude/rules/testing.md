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
Loaded when the agent opens a test file. This repo has no test suite yet, so nothing below fires;
the file is here as the shape to fill in when the first test appears. At that point: set `paths` to
the real test layout, fill in the command table, and move the general testing rules (tests verify
the solution, stubs, one test per behaviour) into AGENTS.md, where they bind implementation code
too.
-->

| Purpose | Command |
|---|---|
| Single test by name | fill this in with the first test file — see the comment above |
| Whole suite | fill this in with the first test file — see the comment above |

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
