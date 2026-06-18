from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel


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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
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
                (incident_id, trace_id, status, report_json, eval_json, markdown_report)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result.incident_id,
                    result.trace_id,
                    result.workflow_status,
                    json.dumps(result.report, default=_json_default, ensure_ascii=False),
                    json.dumps(result.eval_report, default=_json_default, ensure_ascii=False),
                    result.markdown_report,
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
