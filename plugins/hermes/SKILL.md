---
name: skillopt-sleep-hermes
description: "Use when the user wants their Hermes Agent to self-improve from past usage, asks about a nightly/offline 'sleep' cycle for Hermes, wants Hermes to review past sessions, learn preferences, or consolidate memory/skills, or to run dry-run/run/adopt/status for SkillOpt-Sleep against Hermes. Drives the skillopt_sleep engine with --source hermes and --backend hermes: harvest past Hermes sessions via `hermes sessions export` -> mine recurring tasks -> replay through the Hermes CLI -> stage validated skill/memory edits behind a held-out gate."
---

# SkillOpt-Sleep: usage-driven self-evolution for a Hermes Agent

SkillOpt-Sleep gives a Hermes Agent a sleep cycle. On demand or on a nightly
schedule it reviews past Hermes sessions, re-runs recurring tasks through the
Hermes CLI, and proposes bounded edits to a configured skill and memory doc.
With the validation gate enabled it keeps only changes that improve a held-out
score. Live files change only through an explicit `adopt`, which backs up first.

Hermes is first-class here: the harvester and backend live in the shared engine
(`skillopt_sleep/harvest_hermes.py`, `HermesBackend`), so the standard CLI works.
The harvester uses `hermes sessions export` rather than reading the state DB, so
it survives Hermes schema changes and reuses Hermes's own secret redaction.

## Actions

- `status` — nights run so far + the latest staged proposal.
- `dry-run` — harvest + mine + replay, report only (no staging). Safe, no writes.
- `run` — full cycle; stages a reviewed proposal.
- `adopt` — apply the latest staged proposal (backup taken first).
- `harvest` — debug: list recurring tasks mined from recent sessions.
- `schedule` / `unschedule` — manage a nightly cron entry.

## Usage

```bash
# free preview
python -m skillopt_sleep dry-run --backend mock --source hermes --scope all

# real cycle through the Hermes CLI (stages only)
SKILLOPT_SLEEP_HERMES_PROFILE=default \
  python -m skillopt_sleep run --backend hermes --source hermes

python -m skillopt_sleep status
python -m skillopt_sleep adopt
```

Or wire the MCP server (`mcp_server.py`) into your client; cycle tools default to
`backend=hermes` / `source=hermes`.

## Configuration

`HERMES_HOME` (state DB dir, default `~/.hermes`), `HERMES_BIN` (default `hermes`),
`SKILLOPT_SLEEP_HERMES_PROFILE` (profile for cycle calls, default `default`),
`SKILLOPT_SLEEP_HERMES_MODEL` (optional model hint).

## Safety

Sessions are read-only; secrets are redacted before persistence; the engine's own
throwaway sessions are skipped. Harvested text is untrusted — keep tools/plugins
disabled while replaying it. Nothing live changes without `adopt`.
