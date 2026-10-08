"""SQLite journal. Every operation transition and its event commit together."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from rebound.models import Step


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                    steps TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    step_key TEXT NOT NULL, tool TEXT NOT NULL, arguments TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    approved INTEGER NOT NULL DEFAULT 0, error TEXT,
                    UNIQUE(run_id, step_key)
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL,
                    operation_id TEXT, payload TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS event_run ON events(run_id, seq);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _event(self, db, run_id, kind, operation_id=None, payload=None):
        now = time.time()
        db.execute(
            "INSERT INTO events(run_id,kind,operation_id,payload,created_at) VALUES(?,?,?,?,?)",
            (run_id, kind, operation_id, encode(payload or {}), now),
        )
        db.execute("UPDATE runs SET updated_at=? WHERE id=?", (now, run_id))

    def create_run(self, steps: list[Step], title: str = "Untitled run", metadata=None) -> str:
        steps = [Step.model_validate(s) for s in steps]
        if len({s.key for s in steps}) != len(steps):
            raise ValueError("step keys must be unique within a run")
        run_id = "run_" + uuid.uuid4().hex
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                (run_id, title, "pending", encode([s.model_dump() for s in steps]), now, now,
                 encode(metadata or {})),
            )
            for step in steps:
                self._add_operation(db, run_id, step)
            self._event(db, run_id, "run.created", payload={"steps": len(steps)})
        return run_id

    def _add_operation(self, db, run_id, step):
        db.execute(
            "INSERT INTO operations(id,run_id,step_key,tool,arguments,status) VALUES(?,?,?,?,?,?)",
            ("op_" + uuid.uuid4().hex, run_id, step.key, step.tool, encode(step.arguments), "planned"),
        )

    def append_step(self, run_id: str, step: Step):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT steps,status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] == "cancelled":
                raise ValueError("cannot append a step to a cancelled run")
            steps = json.loads(row[0])
            existing = next((s for s in steps if s["key"] == step.key), None)
            if existing:
                if existing != step.model_dump():
                    raise ValueError("logical step key reused with different arguments")
                return
            steps.append(step.model_dump())
            db.execute("UPDATE runs SET steps=?,status='pending' WHERE id=?", (encode(steps), run_id))
            self._add_operation(db, run_id, step)
            self._event(db, run_id, "step.appended", payload=step.model_dump())

    def event(self, run_id, kind, operation_id=None, payload=None):
        with self.connect() as db:
            self._event(db, run_id, kind, operation_id, payload)

    def set_status(self, run_id: str, status: str):
        with self.connect() as db:
            # Serialize the read and write with cancellation from other processes.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row[0] == "cancelled" and status != "cancelled":
                return
            db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
            self._event(db, run_id, "run." + status)

    def metadata(self, run_id, updates: dict):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT metadata FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            data = json.loads(row[0])
            data.update(updates)
            db.execute("UPDATE runs SET metadata=? WHERE id=?", (encode(data), run_id))

    def transition(self, operation_id, status, *, result=None, error=None, increment=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            op = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            if op is None:
                raise KeyError(operation_id)
            self._transition(db, op, status, result=result, error=error, increment=increment)

    def _transition(self, db, op, status, *, result=None, error=None, increment=False):
        if op["status"] == "succeeded":
            raise ValueError("committed operation result is immutable")
        if status == "dispatched":
            run = db.execute("SELECT status FROM runs WHERE id=?", (op["run_id"],)).fetchone()
            if run["status"] == "cancelled":
                raise ValueError("cannot dispatch a cancelled run")
        db.execute(
            "UPDATE operations SET status=?,result=?,error=?,attempts=attempts+? WHERE id=?",
            (status, encode(result) if result is not None else None, error, int(increment), op["id"]),
        )
        payload = {"status": status, "attempt": op["attempts"] + int(increment)}
        if result is not None:
            payload["result"] = result
        if error:
            payload["error"] = error
        self._event(db, op["run_id"], "operation." + status, op["id"], payload)

    def reconcile(self, run_id: str, operation_id: str, result: dict, note: str):
        """Commit the human assertion and confirmed result as one transaction."""
        if not isinstance(result, dict) or not note.strip():
            raise ValueError("manual reconciliation requires a result object and an evidence note")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            op = db.execute(
                "SELECT * FROM operations WHERE id=? AND run_id=?", (operation_id, run_id)
            ).fetchone()
            if op is None or op["status"] not in {"unknown", "dispatched"}:
                raise ValueError("only an uncertain operation in this run can be reconciled")
            self._event(db, run_id, "recovery.manual", operation_id, {"note": note, "result": result})
            self._transition(db, op, "succeeded", result=result)

    def approve(self, run_id: str, operation_id: str):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE operations SET approved=1 WHERE id=? AND run_id=? AND status='planned'",
                (operation_id, run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("approval requires a planned operation belonging to this run")
            self._event(db, run_id, "operation.approved", operation_id)

    def list_runs(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 500").fetchall()
        return [self._decode_run(row) for row in rows]

    @staticmethod
    def _decode_run(row):
        data = dict(row)
        data["steps"] = json.loads(data["steps"])
        data["metadata"] = json.loads(data["metadata"])
        return data

    def snapshot(self, run_id: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            data = self._decode_run(row)
            operations = db.execute("SELECT * FROM operations WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
            events = db.execute("SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        data["operations"] = []
        for row in operations:
            op = dict(row)
            op["arguments"] = json.loads(op["arguments"])
            op["result"] = json.loads(op["result"]) if op["result"] is not None else None
            op["approved"] = bool(op["approved"])
            data["operations"].append(op)
        data["events"] = [{**dict(row), "payload": json.loads(row["payload"])} for row in events]
        return data
