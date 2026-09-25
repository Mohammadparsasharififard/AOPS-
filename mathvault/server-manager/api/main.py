"""FastAPI app — Personal Server Manager.

Endpoints:
- POST /api/auth/setup          — set master password (first run only)
- POST /api/auth/login          — unlock with master password → session cookie
- POST /api/auth/logout         — clear session cookie
- GET  /api/auth/status         — current session state

- GET  /api/servers             — list registered servers
- POST /api/servers             — register a new server
- GET  /api/servers/{id}        — server detail
- PUT  /api/servers/{id}        — update server
- DELETE /api/servers/{id}      — remove server
- GET  /api/servers/{id}/status — live status (CPU/mem/disk)
- POST /api/servers/{id}/test  — test SSH connection

- GET  /api/servers/{id}/deployments
- POST /api/servers/{id}/deployments
- POST /api/servers/{id}/deployments/{dep_id}/run  — run a deployment

- POST /api/servers/{id}/run   — run arbitrary shell command
- GET  /api/servers/{id}/services — list active systemd services
- POST /api/servers/{id}/services/{name}/{action} — start/stop/restart/status

- GET  /api/audit               — recent audit log entries
- GET  /api/archive/offline-url — link to MathVault offline archive (configurable)
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import routes
from config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Personal Server Manager",
        version="1.0.0",
        description="Laptop-side control panel for SSH-reachable personal servers.",
        docs_url="/api/docs" if settings.app_debug else "/api/docs",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(routes.auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(routes.servers.router, prefix="/api/servers", tags=["servers"])
    app.include_router(routes.audit.router, prefix="/api/audit", tags=["audit"])
    app.include_router(routes.archive.router, prefix="/api/archive", tags=["archive"])

    # Serve the built-in web UI at /
    from fastapi.responses import HTMLResponse, FileResponse
    from pathlib import Path

    @app.get("/", response_class=HTMLResponse)
    async def web_ui():
        ui_path = Path(__file__).parent.parent / "static" / "index.html"
        if ui_path.exists():
            return HTMLResponse(ui_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>MathVault API</h1><p>Web UI not found. Visit /api/docs</p>")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.exception_handler(401)
    async def _401(_: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=401)

    return app


app = create_app()
