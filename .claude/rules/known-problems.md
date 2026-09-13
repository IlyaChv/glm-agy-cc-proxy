---
paths:
  - "<path/to/legacy>/**"
  - "<path/to/other-legacy-area>/**"
---

# Known problems — do not touch without understanding

<!--
Deployed to .claude/rules/known-problems.md. Loaded only when the agent opens a file under one of
the paths above — today the `paths` list above is a placeholder (this project has no legacy area
yet), so this rule never fires for any file. Keep the `paths` list in sync with the table: a row
whose path is not listed is never seen. Whoever adds the first real row must replace the
placeholder `paths` entries in that same commit.
One row per oddity. Owner and date are mandatory — an unowned, undated list becomes a graveyard
nobody dares to clean up.
-->

You are inside an area that is odd on purpose. Each row below says what is odd, why it is like
that, and what breaks when it is "fixed" naively.

| Area | Why it is like this / what breaks | Owner | Reviewed |
|---|---|---|---|
| `<legacy field X>` | `<e.g. downstream report expects the old name; renaming silently zeroes Q-reports>` | `<@name>` | `<YYYY-MM>` |
| `<path/to/other-legacy-area>/` | `<...>` | `<@name>` | `<YYYY-MM>` |

Before changing anything here: read the matching row and the ADR it points to (if any), then say
in the task thread which row you are working around and how. If the change requires undoing what
a row protects, that is an ADR change — stop and ask.

*Why: these areas already cost an incident once. The row is the memory of that incident; a fix that
ignores it repeats it.*
