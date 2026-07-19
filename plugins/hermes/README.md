# SkillOpt-Sleep — Hermes Agent integration

First-class integration of the [Hermes Agent](https://github.com/NousResearch/Hermes)
CLI with the shared `skillopt_sleep` engine. Unlike the reference OpenClaw adapter,
Hermes is wired directly into core: `--source hermes` and `--backend hermes` work from
the shared CLI, alongside `claude` and `codex`.

## What you get

- **Harvester** (`skillopt_sleep/harvest_hermes.py`) — shells out to the stable
  `hermes sessions export --format jsonl --redact` interface (schema-drift-proof,
  WAL-safe, self-redacting), normalizes sessions into `SessionDigest` records,
  layers its own sanitization, and skips the engine's own throwaway sessions.
  Warns loudly (never silently) when nothing is harvestable.
- **Backend** (`HermesBackend` in `skillopt_sleep/backend.py`) — drives
  `hermes --profile <name> chat -Q -q "<prompt>"` for the replay/reflect phases.
- **MCP server** (`mcp_server.py`) — exposes the cycle as MCP tools with Hermes
  defaults, so any MCP client can run it.

## Requirements

- Python 3.10+
- The `hermes` CLI installed and authenticated, with at least one profile.
- Past Hermes **CLI** sessions with message content (`hermes sessions list` should
  show non-empty sessions; ACP/editor-bridge sessions carry no harvestable turns).
  Override the home with `HERMES_HOME`.

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

## What gets evolved (and why)

The Hermes integration evolves **the skill only**, written to where Hermes actually
discovers global skills:

```
~/.hermes/skills/skillopt-sleep-learned/SKILL.md
```

The MCP server sets `--target-skill-path` there by default. Run it manually with:

```bash
python -m skillopt_sleep run --backend hermes --source hermes --no-evolve-memory \
  --target-skill-path ~/.hermes/skills/skillopt-sleep-learned/SKILL.md
```

**Memory is left to Hermes.** The shared engine's memory evolution targets a project
`CLAUDE.md`, which Hermes does not read — Hermes manages its own memory via `SOUL.md`
/ `MEMORY.md` and its `curator`/`learning` subsystems. So the Hermes path defaults to
`--no-evolve-memory` (skill-only) rather than staging a doc Hermes would ignore. Proper
`AGENTS.md` memory support depends on a future engine `memory_filename` option and is
intentionally out of scope here.

## Safety

Sessions are harvested read-only and secrets are redacted before anything is persisted.
The cycle stages proposals; `adopt` is required to change any live file and always backs
it up first. Harvested text is untrusted — keep tools/plugins disabled when replaying it.
