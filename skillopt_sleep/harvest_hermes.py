"""SkillOpt-Sleep Hermes Agent session harvesting.

Harvests Hermes Agent sessions into ``SessionDigest`` records via the stable,
purpose-built ``hermes sessions export --format jsonl`` interface rather than
reading ``~/.hermes/state.db`` directly. That command is schema-drift-proof,
handles WAL concurrency safely, and applies Hermes's own secret redaction
(``--redact``); we layer our own sanitization on top as defense in depth.

Each exported JSONL line is one session dict (id, source, cwd, title,
started_at, ended_at, ... plus a ``messages`` array). Tool arguments and raw
tool outputs are not copied; only tool *names* are kept.

If the ``hermes`` binary is missing, the export fails, or nothing matches, this
warns to stderr and returns ``[]`` — a no-op, never a silent success.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from skillopt_sleep.harvest import _detect_feedback, _is_meta_prompt, _project_matches
from skillopt_sleep.staging import _SECRET_PATTERNS
from skillopt_sleep.types import SessionDigest

HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


class HarvestExportError(RuntimeError):
    """The ``hermes sessions export`` subprocess failed (missing binary, non-zero
    exit, or timeout). Distinct from a *successful but empty* export so callers
    don't advance the harvest window past sessions they never actually scanned.
    """


def _warn(msg: str) -> None:
    print(f"[sleep] hermes harvest: {msg}", file=sys.stderr)


def _sanitize_text(text: str) -> str:
    """Redact secrets; return "" for meta prompts (slash commands, pastes, etc.)."""
    sanitized = (text or "").strip()
    if not sanitized or _is_meta_prompt(sanitized):
        return ""
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _dedup(xs: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _message_text(content: Any) -> str:
    """Normalize a message ``content`` field (string | parts list | dict)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                val = part.get("text") or part.get("content")
                if isinstance(val, str):
                    parts.append(val)
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        val = content.get("text") or content.get("content")
        return val if isinstance(val, str) else ""
    return str(content)


def _run_export(
    *,
    hermes_home: str,
    since_iso: Optional[str],
    cwd_filter: str,
    min_messages: int,
) -> Optional[str]:
    """Run ``hermes sessions export`` and return raw JSONL, or None on failure.

    Isolated so tests can patch it without a real ``hermes`` binary.
    """
    hermes_bin = os.environ.get("HERMES_BIN", "hermes")
    with tempfile.NamedTemporaryFile("r", suffix=".jsonl", delete=True) as tf:
        cmd = [hermes_bin, "sessions", "export", tf.name,
               "--format", "jsonl", "--redact",
               "--min-messages", str(max(1, min_messages))]
        if since_iso:
            cmd += ["--after", since_iso]
        if cwd_filter:
            cmd += ["--cwd", cwd_filter]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                env={**os.environ, "HERMES_HOME": hermes_home, "HERMES_NO_COLOR": "1"},
            )
        except FileNotFoundError:
            _warn(f"'{hermes_bin}' not found on PATH; is Hermes Agent installed?")
            return None
        except Exception as exc:  # noqa: BLE001
            _warn(f"export failed: {exc}")
            return None
        if proc.returncode != 0:
            _warn((proc.stderr or "").strip()[:300] or f"export exited {proc.returncode}")
            return None
        try:
            with open(tf.name, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            _warn(f"could not read export output: {exc}")
            return None


def _ts(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _build_digest(
    session: Dict[str, Any],
    *,
    scope: str,
    invoked_project: str,
) -> Optional[SessionDigest]:
    """Build a ``SessionDigest`` from one exported session dict, or None."""
    session_id = str(session.get("id") or session.get("session_id") or "")
    project = (session.get("cwd") or "").strip()
    # Never harvest the optimizer's own calls (HermesBackend runs in these tempdirs).
    if "skillopt_sleep_hermes_" in project:
        return None

    user_prompts: List[str] = []
    assistant_finals: List[str] = []
    tools: List[str] = []
    feedback_signals: List[str] = []
    n_user = 0
    n_asst = 0
    last_assistant = ""

    for msg in session.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = (msg.get("role") or "").strip()
        content = _message_text(msg.get("content")).strip()
        tool = (msg.get("tool_name") or "").strip()

        if role == "user" and content:
            sanitized = _sanitize_text(content)
            if sanitized:
                n_user += 1
                user_prompts.append(sanitized)
                feedback_signals.extend(_detect_feedback(sanitized))
                if last_assistant:
                    assistant_finals.append(last_assistant)
                    last_assistant = ""
        elif role == "assistant" and content:
            n_asst += 1
            last_assistant = _sanitize_text(content) or ""
        # tool rows contribute only their name; args/outputs are never copied.

        if tool:
            tools.append(tool)

    if last_assistant:
        assistant_finals.append(last_assistant)

    if n_user == 0 and n_asst == 0:
        return None
    if not _project_matches(project, scope, invoked_project):
        return None

    return SessionDigest(
        session_id=session_id,
        project=project,
        started_at=_ts(session.get("started_at")),
        ended_at=_ts(session.get("ended_at")),
        user_prompts=user_prompts,
        assistant_finals=assistant_finals[-5:],
        tools_used=_dedup(tools),
        files_touched=[],
        feedback_signals=feedback_signals,
        n_user_turns=n_user,
        n_assistant_turns=n_asst,
        raw_path=f"hermes:{session_id}",
    )


def harvest_hermes(
    *,
    scope: str = "invoked",
    invoked_project: str = "",
    since_iso: Optional[str] = None,
    limit: int = 0,
    hermes_home: str = "",
) -> List[SessionDigest]:
    """Harvest Hermes sessions via ``hermes sessions export``. ``limit=0`` = no limit.

    ``scope="invoked"`` restricts to sessions whose cwd is under ``invoked_project``
    (Hermes CLI/coding sessions); ``scope="all"`` harvests every session with content.
    """
    home = hermes_home or HERMES_HOME
    cwd_filter = invoked_project if (scope == "invoked" and invoked_project) else ""

    raw = _run_export(
        hermes_home=home,
        since_iso=since_iso,
        cwd_filter=cwd_filter,
        min_messages=1,
    )
    if raw is None:
        # Export failed (see the [sleep] warning already printed by _run_export).
        # Raise instead of returning [] so the caller keeps the harvest window
        # open and retries these sessions next run, rather than skipping them.
        raise HarvestExportError("hermes sessions export failed")

    digests: List[SessionDigest] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            session = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(session, dict):
            continue
        digest = _build_digest(session, scope=scope, invoked_project=invoked_project)
        if digest is not None:
            digests.append(digest)

    if not digests:
        _warn(
            f"no harvestable sessions (scope={scope}"
            + (f", cwd={cwd_filter}" if cwd_filter else "")
            + "). Run some `hermes chat` sessions, or try --scope all."
        )
        return []

    # Most recent first, then apply the cap.
    digests.sort(key=lambda d: d.ended_at or "", reverse=True)
    return digests[:limit] if limit and limit > 0 else digests
