from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.schemas.incident import (
    EvalReport,
    ExternalToolContext,
    HumanApprovalResult,
    IncidentReport,
    IncidentRunResult,
    IncidentRunSummary,
    TraceEvent,
)


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "incidents.db"


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


class IncidentStore:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or DEFAULT_DATABASE_PATH
        self._memory_conn: sqlite3.Connection | None = None
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._init_db()
        except sqlite3.Error:
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        return sqlite3.connect(str(self.database_path))

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incident_runs (
                    incident_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    eval_json TEXT NOT NULL,
                    markdown_report TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    approval_status TEXT NOT NULL DEFAULT 'pending',
                    approved_by TEXT,
                    approval_note TEXT,
                    approval_updated_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_column(conn, "incident_runs", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "incident_runs", "approval_status", "TEXT NOT NULL DEFAULT 'pending'")
            self._ensure_column(conn, "incident_runs", "approved_by", "TEXT")
            self._ensure_column(conn, "incident_runs", "approval_note", "TEXT")
            self._ensure_column(conn, "incident_runs", "approval_updated_at", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def save_run(self, result: Any) -> None:
        try:
            self._save_run(result)
        except sqlite3.Error:
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._init_db()
            self._save_run(result)

    def _save_run(self, result: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO incident_runs
                (incident_id, trace_id, status, report_json, eval_json, markdown_report, metadata_json, approval_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.incident_id,
                    result.trace_id,
                    result.workflow_status,
                    json.dumps(result.report, default=_json_default, ensure_ascii=False),
                    json.dumps(result.eval_report, default=_json_default, ensure_ascii=False),
                    result.markdown_report,
                    json.dumps(result.metadata, default=_json_default, ensure_ascii=False),
                    "pending" if result.report.human_approval_required else "not_required",
                ),
            )
            conn.execute("DELETE FROM trace_events WHERE incident_id = ?", (result.incident_id,))
            conn.executemany(
                """
                INSERT INTO trace_events (incident_id, trace_id, event_json)
                VALUES (?, ?, ?)
                """,
                [
                    (
                        result.incident_id,
                        result.trace_id,
                        json.dumps(event, default=_json_default, ensure_ascii=False),
                    )
                    for event in result.trace_events
                ],
            )

    def list_runs(self, limit: int = 20) -> list[IncidentRunSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT incident_id, trace_id, status, report_json, approval_status, created_at
                FROM incident_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        summaries: list[IncidentRunSummary] = []
        for row in rows:
            report = json.loads(row[3])
            summaries.append(
                IncidentRunSummary(
                    incident_id=row[0],
                    trace_id=row[1],
                    status=row[2],
                    service_name=report.get("service_name", ""),
                    severity=report.get("severity", "unknown"),
                    human_approval_required=bool(report.get("human_approval_required", False)),
                    approval_status=row[4],
                    created_at=row[5],
                )
            )
        return summaries

    def get_run(self, incident_id: str) -> IncidentRunResult | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT incident_id, trace_id, status, report_json, eval_json, markdown_report, metadata_json
                FROM incident_runs
                WHERE incident_id = ?
                """,
                (incident_id,),
            ).fetchone()
            trace_rows = conn.execute(
                """
                SELECT event_json
                FROM trace_events
                WHERE incident_id = ?
                ORDER BY id ASC
                """,
                (incident_id,),
            ).fetchall()
        if row is None:
            return None
        metadata = json.loads(row[6] or "{}")
        tool_context = None
        if isinstance(metadata.get("tool_context"), dict):
            tool_context = ExternalToolContext.model_validate(metadata["tool_context"])
        return IncidentRunResult(
            incident_id=row[0],
            trace_id=row[1],
            workflow_status=row[2],
            report=IncidentReport.model_validate(json.loads(row[3])),
            eval_report=EvalReport.model_validate(json.loads(row[4])),
            markdown_report=row[5],
            tool_context=tool_context,
            metadata=metadata,
            trace_events=[TraceEvent.model_validate(json.loads(item[0])) for item in trace_rows],
        )

    def get_trace(self, incident_id: str) -> list[TraceEvent] | None:
        run = self.get_run(incident_id)
        if run is None:
            return None
        return run.trace_events

    def update_approval(
        self,
        incident_id: str,
        approval_status: str,
        approved_by: str,
        note: str,
    ) -> HumanApprovalResult | None:
        with self._connect() as conn:
            exists = conn.execute("SELECT incident_id FROM incident_runs WHERE incident_id = ?", (incident_id,)).fetchone()
            if exists is None:
                return None
            conn.execute(
                """
                UPDATE incident_runs
                SET approval_status = ?,
                    approved_by = ?,
                    approval_note = ?,
                    approval_updated_at = CURRENT_TIMESTAMP
                WHERE incident_id = ?
                """,
                (approval_status, approved_by, note, incident_id),
            )
            row = conn.execute(
                """
                SELECT incident_id, approval_status, approved_by, approval_note, approval_updated_at
                FROM incident_runs
                WHERE incident_id = ?
                """,
                (incident_id,),
            ).fetchone()
        return HumanApprovalResult(
            incident_id=row[0],
            approval_status=row[1],
            approved_by=row[2] or "",
            note=row[3] or "",
            updated_at=row[4] or "",
        )
