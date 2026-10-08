"""Local inspector API. Serve only on a trusted workstation, normally 127.0.0.1."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from filelock import Timeout
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from rebound.demo import DemoService


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal[
        "clean", "lost_ack", "delayed_visibility", "unavailable", "stale_evidence"
    ] = "lost_ack"
    policy: Literal["evidence", "naive", "checkpoint", "idempotent", "verify", "no_freshness"] = (
        "evidence"
    )
    steps: int = Field(default=8, ge=1, le=100)


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: dict = Field(description="Result independently confirmed by a human operator")
    note: str = Field(min_length=8, max_length=2000)


def create_app(data_dir: Path) -> FastAPI:
    """Build one app and service per local data directory; no browser credentials."""
    app = FastAPI(title="Rebound Harness", version="0.1.0")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    service = DemoService(data_dir)
    mutations = asyncio.Lock()
    app.state.service = service

    @app.middleware("http")
    async def same_origin_mutations(request: Request, call_next):
        # JSON-only, same-origin writes prevent drive-by forms from operating a
        # localhost inspector. This is not a replacement for remote authentication.
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin writes are disabled"}, 403)
            if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                return JSONResponse({"detail": "Use application/json"}, 415)
            size = request.headers.get("content-length", "")
            if not size.isdecimal():
                return JSONResponse({"detail": "A Content-Length header is required"}, 411)
            if int(size) > 65536:
                return JSONResponse({"detail": "Request exceeds 64 KiB"}, 413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "mode": "local", "demo_provider": "simulated"}

    @app.get("/api/runs")
    def runs():
        return service.list_runs()

    def get_snapshot(run_id: str):
        try:
            return service.snapshot(run_id)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, "Run not found") from exc

    @app.get("/api/runs/{run_id}")
    def snapshot(run_id: str):
        return get_snapshot(run_id)

    @app.post("/api/demo", status_code=201)
    async def demo(body: DemoRequest):
        async with mutations:
            return await service.create_demo(**body.model_dump())

    @app.post("/api/runs/{run_id}/resume")
    async def resume(run_id: str):
        async with mutations:
            get_snapshot(run_id)
            try:
                return await service.resume(run_id)
            except (ValueError, RuntimeError, Timeout) as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.post("/api/runs/{run_id}/operations/{operation_id}/resolve")
    async def resolve(run_id: str, operation_id: str, body: ResolutionRequest):
        async with mutations:
            current = get_snapshot(run_id)
            if not any(op["id"] == operation_id for op in current["operations"]):
                raise HTTPException(404, "Operation not found")
            try:
                return await service.resolve(run_id, operation_id, body.result, body.note)
            except (ValueError, RuntimeError, Timeout) as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.get("/api/runs/{run_id}/events")
    def events(
        run_id: str,
        after: int = 0,
        last_event_id: Annotated[str | None, Header()] = None,
    ):
        """Finite SSE snapshot; reconnect with Last-Event-ID or ?after=<seq>.

        This endpoint intentionally closes after currently committed events. The
        inspector polls snapshots every three seconds while a run is active.
        """
        current = get_snapshot(run_id)
        try:
            cursor = max(after, int(last_event_id or 0))
        except ValueError as exc:
            raise HTTPException(400, "Last-Event-ID must be an integer") from exc

        def stream():
            for event in current["events"]:
                if event["seq"] > cursor:
                    yield f"id: {event['seq']}\nevent: trace\ndata: {json.dumps(event)}\n\n"
            yield ": snapshot complete\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    static_dir = Path(__file__).with_name("static")
    if static_dir.is_dir() and (static_dir / "index.html").is_file():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(static_dir / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        def missing_frontend():
            return {
                "message": "Inspector assets are not built. Run pnpm build in frontend/.",
                "api_docs": "/docs",
            }

    return app
