"""SQLite Event Store — SOT per EVENT_SCHEMA_FREEZE v1.0.0."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dsp import EVENT_SCHEMA_VERSION
from dsp.event_store.models import (
    Event,
    EventQuery,
    MetricDef,
    RunClosedError,
    RunNotOpenError,
)

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_schema_version TEXT NOT NULL DEFAULT '1.0.0',
    run_id      TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    stage       TEXT NOT NULL DEFAULT 'main',
    event       TEXT NOT NULL,
    status      TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    artifact    TEXT NOT NULL DEFAULT '',
    evidence    TEXT NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL DEFAULT 'local',
    exit_code   INTEGER,
    tags        TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_scenario ON events(run_id, scenario_id);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(run_id, scenario_id, status);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(run_id, scenario_id, event);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
"""


class EventStore:
    """Append-only SQLite Event Store per run."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._run_id: str | None = None
        self._closed = False

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def is_closed(self) -> bool:
        return self._closed

    def open_run(self, run_id: str, metadata: dict[str, Any] | None = None) -> None:
        if self._conn is not None:
            self._conn.close()
        self._run_id = run_id
        self._closed = False
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_DDL)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("event_schema_version", EVENT_SCHEMA_VERSION),
        )
        if metadata:
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("run_metadata", json.dumps(metadata)),
            )
        self._conn.commit()

    def append(self, event: Event) -> int:
        if self._conn is None or self._run_id is None:
            raise RunNotOpenError("No run is open")
        if self._closed:
            raise RunClosedError("Run is closed — append forbidden")
        event.validate()
        if event.run_id != self._run_id:
            raise ValueError(f"Event run_id {event.run_id!r} does not match open run {self._run_id!r}")

        ts = event.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_str = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        cursor = self._conn.execute(
            """
            INSERT INTO events (
                event_schema_version, run_id, timestamp, scenario_id, stage,
                event, status, target, artifact, evidence, source, exit_code, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_schema_version,
                event.run_id,
                ts_str,
                event.scenario_id,
                event.stage,
                event.event,
                event.status,
                event.target,
                event.artifact,
                json.dumps(event.evidence),
                event.source,
                event.exit_code,
                json.dumps(event.tags),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def count(self, query: EventQuery) -> int:
        where, params = self._build_where(query)
        sql = f"SELECT COUNT(*) FROM events WHERE {where}"
        assert self._conn is not None
        row = self._conn.execute(sql, params).fetchone()
        return int(row[0])

    def aggregate(self, run_id: str, scenario_id: str, metrics: list[MetricDef]) -> dict[str, int | float]:
        result: dict[str, int | float] = {}
        for metric in metrics:
            result[metric.name] = self._compute_metric(run_id, scenario_id, metric)
        return result

    def _compute_metric(self, run_id: str, scenario_id: str, metric: MetricDef) -> int | float:
        assert self._conn is not None
        filt = metric.event_filter
        conditions = ["run_id = ?", "scenario_id = ?"]
        params: list[Any] = [run_id, scenario_id]

        event_val = filt.get("event")
        if event_val is not None:
            if isinstance(event_val, list):
                placeholders = ", ".join("?" for _ in event_val)
                conditions.append(f"event IN ({placeholders})")
                params.extend(event_val)
            else:
                conditions.append("event = ?")
                params.append(event_val)

        status_val = filt.get("status")
        if status_val is not None:
            if isinstance(status_val, list):
                placeholders = ", ".join("?" for _ in status_val)
                conditions.append(f"status IN ({placeholders})")
                params.extend(status_val)
            else:
                conditions.append("status = ?")
                params.append(status_val)

        where = " AND ".join(conditions)

        if metric.aggregate == "count":
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM events WHERE {where}", params
            ).fetchone()
            return int(row[0])

        if metric.aggregate == "sum":
            row = self._conn.execute(
                f"SELECT COALESCE(SUM(CAST(json_extract(evidence, '$.value') AS REAL)), 0) "
                f"FROM events WHERE {where}",
                params,
            ).fetchone()
            return float(row[0])

        if metric.aggregate == "distinct_artifact":
            row = self._conn.execute(
                f"SELECT COUNT(DISTINCT artifact) FROM events WHERE {where} AND artifact != ''",
                params,
            ).fetchone()
            return int(row[0])

        if metric.aggregate == "json_extract":
            if not metric.json_path:
                raise ValueError(f"json_path required for metric {metric.name}")
            json_path = metric.json_path
            if json_path.startswith("$."):
                json_path = "$." + json_path[2:]
            row = self._conn.execute(
                f"SELECT AVG(CAST(json_extract(evidence, ?) AS REAL)) FROM events WHERE {where}",
                [json_path, *params],
            ).fetchone()
            val = row[0]
            return float(val) if val is not None else 0.0

        if metric.aggregate == "ratio":
            num_name = metric.name.replace("_ratio", "_count")
            num_metric = MetricDef(
                name=num_name,
                event_filter=filt,
                aggregate="count",
            )
            denom_filter = dict(filt)
            denom_metric = MetricDef(
                name=f"{metric.name}_denom",
                event_filter=denom_filter,
                aggregate="count",
            )
            num = self._compute_metric(run_id, scenario_id, num_metric)
            denom = self._compute_metric(run_id, scenario_id, denom_metric)
            return float(num) / float(denom) if denom > 0 else 0.0

        raise ValueError(f"Unknown aggregate type: {metric.aggregate}")

    def sample(
        self,
        run_id: str,
        scenario_id: str,
        limit: int = 5,
        event_filter: dict[str, str | list[str]] | None = None,
    ) -> list[Event]:
        assert self._conn is not None
        query = EventQuery(run_id=run_id, scenario_id=scenario_id)
        if event_filter:
            query.event = event_filter.get("event")
            query.status = event_filter.get("status")
        where, params = self._build_where(query)
        sql = f"SELECT * FROM events WHERE {where} ORDER BY id DESC LIMIT ?"
        rows = self._conn.execute(sql, [*params, limit]).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_events(self, run_id: str, scenario_id: str | None = None) -> list[Event]:
        assert self._conn is not None
        if scenario_id:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND scenario_id = ? ORDER BY id",
                (run_id, scenario_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def close_run(self) -> None:
        self._closed = True
        if self._conn:
            self._conn.commit()

    def export_jsonl(self, path: Path) -> None:
        assert self._conn is not None
        assert self._run_id is not None
        events = self.list_events(self._run_id)
        with path.open("w", encoding="utf-8") as fh:
            for ev in events:
                record = {
                    "id": ev.id,
                    "event_schema_version": ev.event_schema_version,
                    "run_id": ev.run_id,
                    "timestamp": ev.timestamp.isoformat().replace("+00:00", "Z"),
                    "scenario_id": ev.scenario_id,
                    "stage": ev.stage,
                    "event": ev.event,
                    "status": ev.status,
                    "target": ev.target,
                    "artifact": ev.artifact,
                    "evidence": ev.evidence,
                    "source": ev.source,
                    "exit_code": ev.exit_code,
                    "tags": ev.tags,
                }
                fh.write(json.dumps(record) + "\n")

    @classmethod
    def open_existing(cls, db_path: Path) -> EventStore:
        store = cls(db_path)
        store._conn = sqlite3.connect(str(db_path))
        store._conn.row_factory = sqlite3.Row
        row = store._conn.execute(
            "SELECT run_id FROM events LIMIT 1"
        ).fetchone()
        if row:
            store._run_id = row["run_id"]
        meta = store._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'run_metadata'"
        ).fetchone()
        store._closed = True
        return store

    def _build_where(self, query: EventQuery) -> tuple[str, list[Any]]:
        conditions = ["run_id = ?"]
        params: list[Any] = [query.run_id]

        if query.scenario_id is not None:
            conditions.append("scenario_id = ?")
            params.append(query.scenario_id)

        if query.stage is not None:
            conditions.append("stage = ?")
            params.append(query.stage)

        if query.event is not None:
            if isinstance(query.event, list):
                placeholders = ", ".join("?" for _ in query.event)
                conditions.append(f"event IN ({placeholders})")
                params.extend(query.event)
            else:
                conditions.append("event = ?")
                params.append(query.event)

        if query.status is not None:
            if isinstance(query.status, list):
                placeholders = ", ".join("?" for _ in query.status)
                conditions.append(f"status IN ({placeholders})")
                params.extend(query.status)
            else:
                conditions.append("status = ?")
                params.append(query.status)

        return " AND ".join(conditions), params

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        ts_raw = row["timestamp"]
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        return Event(
            id=row["id"],
            event_schema_version=row["event_schema_version"],
            run_id=row["run_id"],
            scenario_id=row["scenario_id"],
            timestamp=ts,
            stage=row["stage"],
            event=row["event"],
            status=row["status"],
            target=row["target"],
            artifact=row["artifact"],
            evidence=json.loads(row["evidence"]),
            source=row["source"],
            exit_code=row["exit_code"],
            tags=json.loads(row["tags"]),
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
