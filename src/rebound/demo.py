"""Persistent local demonstration provider. All demo effects are simulated."""

import json
import sqlite3
import time
from pathlib import Path

from rebound.models import Evidence, Step, ToolKind
from rebound.runtime import Runtime
from rebound.store import Store
from rebound.tools import Tool

SCENARIOS = ("clean", "lost_ack", "delayed_visibility", "unavailable", "stale_evidence")


class DemoService:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_dir / "journal.sqlite")
        self.provider_path = self.data_dir / "demo-provider.sqlite"
        with sqlite3.connect(self.provider_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS effects (
                  id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL,
                  arguments TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS probes (operation_id TEXT PRIMARY KEY, count INTEGER NOT NULL);
            """)

    def _tool(self, scenario):
        async def execute(operation_id, arguments):
            with sqlite3.connect(self.provider_path) as db:
                prior = db.execute("SELECT count(*) FROM effects WHERE operation_id=?", (operation_id,)).fetchone()[0]
                cursor = db.execute("INSERT INTO effects(operation_id,arguments,result) VALUES(?,?,?)", (operation_id, json.dumps(arguments), "{}"))
                result = {"ticket_id": f"TKT-{cursor.lastrowid:04d}", "title": arguments.get("title", "Task"), "status": "created"}
                db.execute("UPDATE effects SET result=? WHERE id=?", (json.dumps(result), cursor.lastrowid))
            if arguments.get("inject_fault") and scenario != "clean" and prior == 0:
                raise TimeoutError("simulated provider committed; acknowledgement was lost")
            return result

        async def probe(operation_id):
            now = time.time()
            with sqlite3.connect(self.provider_path) as db:
                db.execute("INSERT INTO probes VALUES(?,1) ON CONFLICT(operation_id) DO UPDATE SET count=count+1", (operation_id,))
                count = db.execute("SELECT count FROM probes WHERE operation_id=?", (operation_id,)).fetchone()[0]
                row = db.execute("SELECT result FROM effects WHERE operation_id=? ORDER BY id LIMIT 1", (operation_id,)).fetchone()
            if scenario == "unavailable":
                raise ConnectionError("simulated receipt service unavailable")
            if scenario == "delayed_visibility" and count < 3:
                return Evidence(operation_id=operation_id, status="absent", authoritative=False, observed_at=now, valid_until=now+30, source="eventually-consistent demo replica")
            if scenario == "stale_evidence":
                return Evidence(operation_id=operation_id, status="committed", result=json.loads(row[0]) if row else None, authoritative=True, observed_at=now-120, valid_until=now-60, source="expired demo receipt")
            return Evidence(operation_id=operation_id, status="committed" if row else "absent", result=json.loads(row[0]) if row else None, authoritative=True, observed_at=now, valid_until=now+30, source="demo provider receipt ledger", final=True)

        return Tool("create_ticket", ToolKind.RECONCILABLE, execute, probe, "Create one simulated ticket")

    def list_runs(self):
        return self.store.list_runs()

    def snapshot(self, run_id):
        snap = self.store.snapshot(run_id)
        op_ids = {o["id"] for o in snap["operations"]}
        with sqlite3.connect(self.provider_path) as db:
            rows = db.execute("SELECT operation_id,count(*) FROM effects GROUP BY operation_id").fetchall()
        counts = [count for op_id, count in rows if op_id in op_ids]
        snap["metrics"] = {
            "effects": sum(counts), "duplicate_effects": sum(max(0, c-1) for c in counts),
            "completed_steps": sum(o["status"] == "succeeded" for o in snap["operations"]),
            "total_steps": len(snap["operations"]),
            "probes": sum(e["kind"].startswith("recovery.probe") for e in snap["events"]),
            "recovery_decisions": sum(e["kind"] == "recovery.decision" for e in snap["events"]),
            "elapsed_ms": round((snap["updated_at"] - snap["created_at"]) * 1000, 1),
        }
        return snap

    async def create_demo(self, scenario="lost_ack", policy="evidence", steps=8):
        if scenario not in SCENARIOS or not 1 <= steps <= 200:
            raise ValueError("invalid scenario or step count (1..200)")
        workflow = [Step(key=f"step-{i+1}", tool="create_ticket", arguments={"title": f"Review artifact {i+1:02d}", "inject_fault": i == steps//2}) for i in range(steps)]
        run_id = self.store.create_run(workflow, title=f"{scenario.replace('_', ' ').title()} · {steps} steps", metadata={"scenario": scenario, "policy": policy, "simulated": True, "mode": "demo"})
        await Runtime(self.store, [self._tool(scenario)], policy=policy).run(run_id)
        return self.snapshot(run_id)

    async def resume(self, run_id):
        snap = self.store.snapshot(run_id)
        if snap["metadata"].get("mode") != "demo":
            raise ValueError("this endpoint only resumes local demo runs; use the originating adapter")
        await Runtime(self.store, [self._tool(snap["metadata"]["scenario"])], policy=snap["metadata"]["policy"]).run(run_id)
        return self.snapshot(run_id)

    async def resolve(self, run_id, operation_id, result, note):
        snap = self.store.snapshot(run_id)
        if snap["metadata"].get("mode") != "demo":
            raise ValueError("manual demo resolution requires a demo run")
        await Runtime(self.store, [self._tool(snap["metadata"]["scenario"])], policy=snap["metadata"]["policy"]).resolve(run_id, operation_id, result, note)
        return self.snapshot(run_id)

