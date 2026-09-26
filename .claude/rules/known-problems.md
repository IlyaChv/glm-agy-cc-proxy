---
paths:
  # - "path/to/legacy-area/**"   the first real path goes here, in the commit that adds the first row
---

# Known problems — read the row before you change the area

<!--
Deployed to .claude/rules/known-problems.md. Loaded only when the agent opens a file under one of
the paths above — today there is no path and no row (this project has no legacy area yet), so this
rule never fires for any file. Keep the `paths` list in sync with the table: a row whose path is
not listed is never seen, so whoever adds the first row uncomments and fills the `paths` entry in
that same commit.
One row per oddity. Owner and date are mandatory — an unowned, undated list becomes a graveyard
nobody dares to clean up.
-->

You are inside an area that is odd on purpose. Each row below says what is odd, why it is like
that, and what breaks when it is "fixed" naively.

| Area | Why it is like this / what breaks | Owner | Reviewed |
|---|---|---|---|

Before changing anything here: read the matching row and the ADR it points to (if any), then say
in the task thread which row you are working around and how. If the change requires undoing what
a row protects, that is an ADR change — stop and ask.

*Why: these areas already cost an incident once. The row is the memory of that incident; a fix that
ignores it repeats it.*
