@AGENTS.md

<!--
Instance of the pack's template/CLAUDE.md. Machine-wide harness rules (file writes, delegation,
models, memory) come from the user-level ~/.claude/CLAUDE.md, installed from
`agent rules/user/CLAUDE.md`; this file holds only what is specific to this repository.
-->

## Claude Code specifics

- **The skills `glm` and `agy` are edited here, at `.claude/skills/<name>/`;** `~/.claude/skills/`
  holds junctions to them. The wrappers are edited in `GLM/` and `AGY/`; after a change run
  `python tools/install.py machine` in `agent rules` to refresh the installed copies in
  `~/.claude/bin`, then `python tools/check.py` there.
  *Why: an installed copy that lags its source is the one the drivers actually run.*
- **How a worker is called** — from its driver, which loads the `glm` or `agy` skill first — is in
  AGENTS.md, "Division of labour"; installed copies and junctions are recorded in `GLM/README.md`
  and `AGY/README.md`.
