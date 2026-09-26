---
paths:
  - "tests/**"
---

# Editing tests

The suite is `unittest` (stdlib only), one file per area in `tests/`. It never calls `claude`,
`agy` or the network: the key reader, binary lookup and `subprocess` are stubbed where a test
reaches them.

| Purpose | Command |
|---|---|
| Single test by name | `python -m unittest tests.<module>.<Class>.<test>` |
| Whole suite | `python -m unittest discover -s tests` |

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
