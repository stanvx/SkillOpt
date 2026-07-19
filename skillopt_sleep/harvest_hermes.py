"""SkillOpt-Sleep Hermes Agent session harvesting.

Reads transcripts from the Hermes Agent state database (``~/.hermes/state.db``)
and normalizes them into ``SessionDigest`` records, without copying tool
arguments or raw tool outputs. User prompts and assistant finals are sanitized
(secret redaction + meta-prompt filtering) exactly as the Codex harvester does.

Engine-manufactured sessions (the throwaway ``skillopt_sleep_hermes_`` tempdirs
that ``HermesBackend`` runs in) are skipped so the optimizer never harvests its
own calls.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from skillopt_sleep.harvest import _detect_feedback, _is_meta_prompt, _project_matches
from skillopt_sleep.staging import _SECRET_PATTERNS
from skillopt_sleep.types import SessionDigest

HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
STATE_DB = os.path.join(HERMES_HOME, "state.db")


def _sanitize_text(text: str) -> str:
    """Redact secrets; return "" for meta prompts (slash commands, pastes, etc.)."""
    sanitized = text.strip()
    if not sanitized or _is_meta_prompt(sanitized):
        return ""
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _is_engine_session(cwd: str) -> bool:
    """True if a session was created by HermesBackend's own optimizer/target calls."""
    return "skillopt_sleep_hermes_" in (cwd or "")


def _dedup(xs: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _ts_from_epoch(epoch: Any) -> str:
    if epoch is None:
        return ""
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _epoch_from_iso(iso: str) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _fetch_sessions(db_path: str, *, since_epoch: Optional[float] = None, limit: int = 0) -> List[Dict[str, Any]]:
    """Sessions with a cwd and an end timestamp, newest first."""
    where = "cwd IS NOT NULL AND cwd != '' AND ended_at IS NOT NULL"
    params: List[Any] = []
    if since_epoch is not None:
        where += " AND ended_at >= ?"
        params.append(since_epoch)
    actual_limit = limit if limit and limit > 0 else 999999
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT id, cwd, title, started_at, ended_at FROM sessions "
            f"WHERE {where} ORDER BY ended_at DESC LIMIT ?",
            params + [actual_limit],
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def _fetch_messages(db_path: str, session_id: Any) -> List[Dict[str, Any]]:
    """User/assistant/tool messages for one session, in order."""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content, tool_name, timestamp FROM messages "
            "WHERE session_id = ? AND role IN ('user', 'assistant', 'tool') ORDER BY id",
            (session_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def _build_digest(
    session: Dict[str, Any],
    messages: List[Dict[str, Any]],
    *,
    scope: str = "invoked",
    invoked_project: str = "",
) -> Optional[SessionDigest]:
    """Build a ``SessionDigest`` for one session, or None if empty / out of scope."""
    session_id = session.get("id")
    project = (session.get("cwd") or "").strip()

    user_prompts: List[str] = []
    assistant_finals: List[str] = []
    tools: List[str] = []
    feedback_signals: List[str] = []
    n_user = 0
    n_asst = 0
    last_assistant = ""

    for msg in messages:
        role = (msg.get("role") or "").strip()
        content = (msg.get("content") or "").strip()
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
        # tool rows contribute only their name; outputs/args are never copied.

        if tool:
            tools.append(tool)

    if last_assistant:
        assistant_finals.append(last_assistant)

    if n_user == 0 and n_asst == 0:
        return None
    if not _project_matches(project, scope, invoked_project):
        return None

    return SessionDigest(
        session_id=str(session_id),
        project=project,
        started_at=_ts_from_epoch(session.get("started_at")),
        ended_at=_ts_from_epoch(session.get("ended_at")),
        user_prompts=user_prompts,
        assistant_finals=assistant_finals[-5:],
        tools_used=_dedup(tools),
        files_touched=[],
        feedback_signals=feedback_signals,
        n_user_turns=n_user,
        n_assistant_turns=n_asst,
        raw_path=f"{STATE_DB}:{session_id}",
    )


def harvest_hermes(
    *,
    scope: str = "invoked",
    invoked_project: str = "",
    since_iso: Optional[str] = None,
    limit: int = 0,
    db_path: str = "",
) -> List[SessionDigest]:
    """Walk the Hermes state DB and return digests. ``limit=0`` means no limit."""
    db = db_path or STATE_DB
    if not os.path.isfile(db):
        return []

    since_epoch = _epoch_from_iso(since_iso) if since_iso else None
    sessions = _fetch_sessions(db, since_epoch=since_epoch, limit=limit)

    digests: List[SessionDigest] = []
    for s in sessions:
        if _is_engine_session(s.get("cwd") or ""):
            continue
        digest = _build_digest(
            s,
            _fetch_messages(db, s.get("id")),
            scope=scope,
            invoked_project=invoked_project,
        )
        if digest is not None:
            digests.append(digest)
    return digests
