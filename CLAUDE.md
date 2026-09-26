@AGENTS.md

<!--
Instance of the pack's template/CLAUDE.md. Machine-wide harness rules (file writes, delegation,
models, memory) come from the user-level ~/.claude/CLAUDE.md, installed from
`agent rules/user/CLAUDE.md`; this file holds only what is specific to this repository.
-->

## Claude Code specifics

- **This repository is the plugin `workers`, loaded in place** through the junction
  `~/.claude/skills/workers`. Skills are edited at `skills/<name>/`, driver agents at `agents/`,
  wrappers in `GLM/` and `AGY/`; there are no installed copies to refresh. After an edit, run
  `/reload-plugins` (or start a new session) so the running session picks it up.
  *Why: a session keeps the plugin as it was loaded; testing an edit without reloading tests the
  old version.*
- **How a worker is called** — from its driver, which loads the `glm` or `agy` skill first — is in
  AGENTS.md, "Division of labour"; the junction and the permission entries are recorded in
  `GLM/README.md` and `AGY/README.md`.
