<!-- Paste into your Hermes AGENTS.md (or project rules) to expose SkillOpt-Sleep. -->

## SkillOpt-Sleep (self-evolution)

This project is wired for SkillOpt-Sleep via the `skillopt-sleep-hermes` MCP server.
Overnight, Sleep reads recent Hermes sessions, mines recurring tasks, replays them,
and proposes bounded edits to the target skill/memory doc. Edits are validated behind
a held-out gate and **staged** — nothing live changes until explicitly adopted.

- Ask for `sleep_status` to see nights run and any staged proposal.
- Ask for `sleep_dry_run` to preview a cycle without staging (safe, no writes).
- Ask for `sleep_run` to run a full cycle and stage a proposal.
- Ask for `sleep_adopt` to apply the latest staged proposal (a backup is made first).

Backend and transcript source default to `hermes`. Set `SKILLOPT_SLEEP_HERMES_PROFILE`
to pick the Hermes profile used for optimizer/target calls, and `HERMES_HOME` if your
state DB lives outside `~/.hermes`.
