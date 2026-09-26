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
the real test layout, fill in the command table. The general rules (tests verify the solution, stubs) are already in
AGENTS.md, "Development rules"; add "new behaviour ships with a test that fails without the
change" there when the first test lands.
-->

| Purpose | Command |
|---|---|
| Single test by name | fill this in with the first test file — see the comment above |
| Whole suite | fill this in with the first test file — see the comment above |

- **Keep a failing test's assertion as strong as it is.** If it fails, the fix goes in the code;
  loosening an assertion, adding a skip/xfail, widening a matcher, or replacing a real call with a
  mock to get green is a defect. If the test itself is wrong, say so and stop.
  *Why: this converts a caught bug into an uncaught one and removes the signal that would have found
  it again.*
- **Changing an existing test is a separate commit** with the reason in the body: what the test used
  to guarantee, why that guarantee is wrong or has moved.
  *Why: it makes the one dangerous kind of diff visible in review instead of buried in a feature.*
- **Copy the structure of the closest existing test in this directory** for anything new here.
  *Why: a suite with three styles is a suite nobody maintains.*
