# SkillOpt-Sleep — Hermes Agent integration

First-class integration of the [Hermes Agent](https://github.com/NousResearch/Hermes)
CLI with the shared `skillopt_sleep` engine. Unlike the reference OpenClaw adapter,
Hermes is wired directly into core: `--source hermes` and `--backend hermes` work from
the shared CLI, alongside `claude` and `codex`.

## What you get

- **Harvester** (`skillopt_sleep/harvest_hermes.py`) — reads the Hermes state DB
  (`~/.hermes/state.db`), normalizes sessions into `SessionDigest` records, redacts
  secrets, and skips the engine's own throwaway sessions.
- **Backend** (`HermesBackend` in `skillopt_sleep/backend.py`) — drives
  `hermes --profile <name> chat -Q -q "<prompt>"` for the replay/reflect phases.
- **MCP server** (`mcp_server.py`) — exposes the cycle as MCP tools with Hermes
  defaults, so any MCP client can run it.

## Requirements

- Python 3.10+
- The `hermes` CLI installed and authenticated, with at least one profile.
- Past Hermes sessions in `~/.hermes/state.db` (override with `HERMES_HOME`).

## Quick start

```bash
# 1. Preview — no API spend, no writes:
python -m skillopt_sleep dry-run --backend mock --source hermes --scope all

# 2. Real cycle through the Hermes CLI, stages a proposal (nothing live changes):
SKILLOPT_SLEEP_HERMES_PROFILE=default \
  python -m skillopt_sleep run --backend hermes --source hermes

# 3. Review, then adopt:
python -m skillopt_sleep status
python -m skillopt_sleep adopt
```

## MCP setup

Copy `mcp-config.example.json` into your client's MCP config (adjust the path), or run
the server directly: `python plugins/hermes/mcp_server.py`. Cycle actions default to
`backend=hermes` / `source=hermes`; pass `backend=mock` for a dry, free run.

## Environment

| Variable | Purpose | Default |
|---|---|---|
| `HERMES_HOME` | Directory holding `state.db` | `~/.hermes` |
| `HERMES_BIN` | Path to the hermes binary | `hermes` |
| `SKILLOPT_SLEEP_HERMES_PROFILE` | Hermes profile for cycle calls | `default` |
| `SKILLOPT_SLEEP_HERMES_MODEL` | Optional model hint | (unset) |

## Safety

Sessions are harvested read-only and secrets are redacted before anything is persisted.
The cycle stages proposals; `adopt` is required to change any live file and always backs
it up first. Harvested text is untrusted — keep tools/plugins disabled when replaying it.
