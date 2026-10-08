"""Scripted workloads served by a separate process with private effect state.

The fixture models transport ambiguity, not model intelligence. The controller may
read ``oracle``; tools passed to a policy expose only execute and probe.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCENARIOS = (
    "clean", "lost_ack", "delayed_visibility", "unavailable",
    "stale_evidence", "no_effect_timeout", "idempotent_lost_ack",
)
FAMILIES = ("data_artifact", "http_ticket", "code_build")


class ProviderState:
    """Provider-owned DB: independent of harness checkpoints and decisions."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "provider.sqlite"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, family TEXT NOT NULL, scenario TEXT NOT NULL,
                    length INTEGER NOT NULL, fault_index INTEGER NOT NULL,
                    triggered INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS effects (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS probes (
                    case_id TEXT NOT NULL, operation_id TEXT NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY(case_id, operation_id));
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def create(self, config: dict[str, Any]) -> dict[str, str]:
        if config["family"] not in FAMILIES or config["scenario"] not in SCENARIOS:
            raise ValueError("unknown fixture")
        case_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO cases(id,family,scenario,length,fault_index) VALUES(?,?,?,?,?)",
                       (case_id, config["family"], config["scenario"], config["length"], config["fault_index"]))
        (self.directory / case_id).mkdir()
        return {"case_id": case_id}

    def _effect(self, case: sqlite3.Row, operation_id: str, index: int) -> dict[str, Any]:
        effect_id = str(uuid.uuid4())
        result = {"effect_id": effect_id, "index": index, "value": (index + 1) ** 2}
        directory = self.directory / case["id"]
        family = case["family"]
        if family == "data_artifact":
            # An append-only export: replay creates an observable duplicate row.
            with (directory / "export.jsonl").open("a") as handle:
                handle.write(json.dumps(result) + "\n")
        elif family == "http_ticket":
            # The provider's effects table is the independent ticket database.
            result["title"] = f"Review batch {index}"
        elif family == "code_build":
            # A real subprocess runs trusted generated fixture code, without a sandbox.
            source = directory / f"build-{effect_id}.py"
            target = directory / f"build-{effect_id}.json"
            source.write_text("import json\nfrom pathlib import Path\n"
                              f"value = ({index} + 1) ** 2\n"
                              f"assert value == {result['value']}\n"
                              f"Path({str(target)!r}).write_text(json.dumps({result!r}))\n")
            subprocess.run([sys.executable, "-I", str(source)], check=True,
                           capture_output=True, timeout=10)
        with self.connect() as db:
            db.execute("INSERT INTO effects VALUES(?,?,?,?,?,?)", (
                effect_id, case["id"], operation_id, index, json.dumps(result), time.time()))
        return result

    def execute(self, case_id: str, operation_id: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """None instructs the HTTP server to drop the response connection."""
        with self.lock, self.connect() as db:
            case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise ValueError("unknown case")
            index = int(arguments["index"])
            trigger = index == case["fault_index"] and not case["triggered"] and case["scenario"] != "clean"
            if trigger:
                db.execute("UPDATE cases SET triggered=1 WHERE id=?", (case_id,))
                db.commit()
            if trigger and case["scenario"] == "no_effect_timeout":
                return None
            if case["scenario"] == "idempotent_lost_ack":
                prior = db.execute("SELECT result FROM effects WHERE case_id=? AND operation_id=? ORDER BY created_at LIMIT 1",
                                   (case_id, operation_id)).fetchone()
                result = json.loads(prior["result"]) if prior else self._effect(case, operation_id, index)
            else:
                result = self._effect(case, operation_id, index)
            return None if trigger else result

    def probe(self, case_id: str, operation_id: str) -> dict[str, Any]:
        with self.lock, self.connect() as db:
            case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                raise ValueError("unknown case")
            db.execute("INSERT INTO probes VALUES(?,?,1) ON CONFLICT(case_id,operation_id) DO UPDATE SET count=count+1",
                       (case_id, operation_id))
            count = db.execute("SELECT count FROM probes WHERE case_id=? AND operation_id=?",
                               (case_id, operation_id)).fetchone()["count"]
            row = db.execute("SELECT * FROM effects WHERE case_id=? AND operation_id=? ORDER BY created_at LIMIT 1",
                             (case_id, operation_id)).fetchone()
            now = time.time()
            evidence: dict[str, Any] = {
                "operation_id": operation_id, "status": "unknown", "result": None,
                "authoritative": False, "observed_at": now, "valid_until": now + 30,
                "source": "http-fixture-provider", "final": False,
            }
            if case["scenario"] == "unavailable":
                return evidence
            if case["scenario"] == "delayed_visibility" and count < 3:
                evidence["status"] = "absent"
                evidence["source"] = "eventually-consistent-search-index"
                return evidence
            if row:
                evidence.update(status="committed", result=json.loads(row["result"]), authoritative=True)
                if case["scenario"] == "stale_evidence":
                    evidence.update(observed_at=now - 120, valid_until=now - 60,
                                    source="expired-provider-receipt-cache")
            else:
                # This is a point-in-time read, never proof a concurrent write cannot finish.
                evidence.update(status="absent", authoritative=True)
            return evidence

    def oracle(self, case_id: str) -> dict[str, Any]:
        with self.lock, self.connect() as db:
            case = dict(db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())
            rows = db.execute("SELECT * FROM effects WHERE case_id=?", (case_id,)).fetchall()
            family = case["family"]
            directory = self.directory / case_id
            if family == "data_artifact":
                export = directory / "export.jsonl"
                physical = [json.loads(line) for line in export.read_text().splitlines()] if export.exists() else []
            elif family == "code_build":
                physical = [json.loads(path.read_text()) for path in directory.glob("build-*.json")]
            else:
                physical = [json.loads(row["result"]) for row in rows]
            indices = [int(item["index"]) for item in physical]
            correct = [item for item in physical if item["value"] == (item["index"] + 1) ** 2]
            expected = set(range(case["length"]))
            seen = set(indices)
            duplicates = sum(max(0, indices.count(index) - 1) for index in seen)
            probe_count = db.execute("SELECT COALESCE(SUM(count),0) AS n FROM probes WHERE case_id=?", (case_id,)).fetchone()["n"]
            return {
                "effects": len(physical), "duplicate_effects": duplicates,
                "missing_effects": len(expected - seen), "unexpected_effects": len(seen - expected),
                "invalid_effects": len(physical) - len(correct), "triggered_faults": case["triggered"],
                "probe_calls": probe_count,
            }


class ProviderHandler(BaseHTTPRequestHandler):
    state: ProviderState

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            route = self.path.strip("/")
            response: dict[str, Any] | None
            if route == "cases":
                response = self.state.create(body)
            elif route == "execute":
                response = self.state.execute(body["case_id"], body["operation_id"], body["arguments"])
                if response is None:
                    self.close_connection = True
                    with contextlib.suppress(OSError):
                        self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
            elif route == "probe":
                response = self.state.probe(body["case_id"], body["operation_id"])
            elif route == "oracle":
                response = self.state.oracle(body["case_id"])
            else:
                self.send_error(404)
                return
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except Exception as error:
            encoded = json.dumps({"error": str(error)}).encode()
            self.send_response(500)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)


def request(base_url: str, route: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(base_url + "/" + route, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read())


class ExternalProvider:
    """Owns a real loopback HTTP subprocess; fixture data stays on disk."""

    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.process: subprocess.Popen[bytes] | None = None
        self.base_url = ""

    def __enter__(self) -> ExternalProvider:
        self.directory.mkdir(parents=True, exist_ok=True)
        ready = self.directory / f"ready-{uuid.uuid4().hex}.json"
        self.process = subprocess.Popen([
            sys.executable, "-m", "rebound.scenarios", "serve", "--directory", str(self.directory),
            "--ready-file", str(ready),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(200):
            if ready.exists():
                self.base_url = json.loads(ready.read_text())["base_url"]
                ready.unlink()
                return self
            if self.process.poll() is not None:
                error = self.process.stderr.read().decode() if self.process.stderr else ""
                raise RuntimeError(f"HTTP fixture exited: {error}")
            time.sleep(0.025)
        self.__exit__(None, None, None)
        raise TimeoutError("HTTP fixture did not start")

    def __exit__(self, *args: Any) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            if self.process.stderr:
                self.process.stderr.close()

    def create(self, **config: Any) -> str:
        return request(self.base_url, "cases", config)["case_id"]

    def oracle(self, case_id: str) -> dict[str, Any]:
        return request(self.base_url, "oracle", {"case_id": case_id})

    def tool(self, case_id: str, scenario: str) -> Any:
        import asyncio

        from rebound.models import Evidence, ToolKind
        from rebound.tools import Tool

        async def execute(operation_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return await asyncio.to_thread(request, self.base_url, "execute", {
                "case_id": case_id, "operation_id": operation_id, "arguments": arguments,
            })

        async def probe(operation_id: str) -> Evidence:
            payload = await asyncio.to_thread(request, self.base_url, "probe", {
                "case_id": case_id, "operation_id": operation_id,
            })
            return Evidence.model_validate(payload)

        kind = ToolKind("idempotent" if scenario == "idempotent_lost_ack" else "reconcilable")
        return Tool(name="fixture_effect", kind=kind, execute=execute, probe=probe,
                    description="Perform one external workload effect; probe its provider receipt.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--ready-file", required=True, type=Path)
    args = parser.parse_args()
    ProviderHandler.state = ProviderState(args.directory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    ready = {"base_url": f"http://127.0.0.1:{server.server_address[1]}", "pid": os.getpid()}
    staging = args.ready_file.with_suffix(".tmp")
    staging.write_text(json.dumps(ready))
    staging.replace(args.ready_file)
    server.serve_forever(poll_interval=0.05)


if __name__ == "__main__":
    main()
