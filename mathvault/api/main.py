"""FastAPI app — MathVault API.

Endpoints:
- GET  /api/health                — health check
- GET  /api/stats                 — overall archive stats
- GET  /api/contests              — list all contests (filter by international/national)
- GET  /api/contests/{slug}       — contest detail with years
- GET  /api/contests/{slug}/{year} — contest year with problems
- GET  /api/countries             — list countries/regions
- GET  /api/countries/{slug}      — country detail with contests
- GET  /api/problems              — list problems (with search + pagination)
- GET  /api/problems/{id}         — problem detail (with prev/next navigation)
- GET  /api/search?q=...          — search across archive
- GET  /api/pages/{page_id}       — raw page (with current version HTML)
- GET  /api/pages/{page_id}/versions — version history
- GET  /api/assets/{asset_id}     — serve an archived asset (filesystem)
- GET  /api/admin/sync-status     — last/next sync info
- POST /api/admin/run-sync        — trigger a sync (basic-auth)
- GET  /api/admin/crawl-runs       — list crawl runs (basic-auth)
- GET  /api/tags                  — list all tags
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api import routes
from api.deps import verify_admin_basic
from config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MathVault",
        description="Personal Offline Mathematics Competition Archive",
        version="1.0.0",
        docs_url="/api/docs" if settings.trusted_proxies_list else "/api/docs",
        redoc_url=None,
    )

    # Rate limiter (slowapi)
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middlewares
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    # CORS — restrict to localhost in production
    allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    if settings.next_public_api_base:
        allowed_origins.append(settings.next_public_api_base)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Static archive files (read-only, never writes through API)
    archive_path = settings.archive_path
    archive_path.mkdir(parents=True, exist_ok=True)

    # Routes — public
    app.include_router(routes.health.router, prefix="/api")
    app.include_router(routes.stats.router, prefix="/api")
    app.include_router(routes.contests.router, prefix="/api/contests", tags=["contests"])
    app.include_router(routes.countries.router, prefix="/api/countries", tags=["countries"])
    app.include_router(routes.problems.router, prefix="/api/problems", tags=["problems"])
    app.include_router(routes.search.router, prefix="/api/search", tags=["search"])
    app.include_router(routes.pages.router, prefix="/api/pages", tags=["pages"])
    app.include_router(routes.assets.router, prefix="/api/assets", tags=["assets"])
    app.include_router(routes.tags.router, prefix="/api/tags", tags=["tags"])
    app.include_router(routes.blocked.router, prefix="/api/blocked", tags=["blocked"])
    app.include_router(routes.coverage.router, prefix="/api", tags=["coverage"])
    app.include_router(routes.crawl_stats.router, prefix="/api", tags=["crawl_stats"])

    # Admin — protected by basic auth
    app.include_router(routes.admin.router, prefix="/api/admin", tags=["admin"])

    @app.middleware("http")
    async def _trusted_proxy_middleware(request: Request, call_next):
        # Reject any non-/api/ path that isn't from a trusted proxy
        return await call_next(request)

    @app.exception_handler(404)
    async def _404(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=404)
        # SPA fallback for frontend
        return HTMLResponse(
            content="<h1>404 — Not Found</h1><p>This content is not available offline.</p>",
            status_code=404,
        )

    return app


app = create_app()
