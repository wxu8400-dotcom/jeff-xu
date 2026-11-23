from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT
from .database import init_db
from .routers import auth, scans, system

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Viral Video Radar API",
        description="TK / INS / YouTube 高播高赞可替换短视频扫描与拆解雷达",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(scans.router)

    if FRONTEND_DIST.exists() and (FRONTEND_DIST / "index.html").exists():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def serve_spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "API not found"})
            candidate = FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(FRONTEND_DIST / "index.html"))
    else:

        @app.get("/", include_in_schema=False)
        def root_fallback():
            return {
                "service": "Viral Video Radar",
                "status": "running",
                "hint": "Frontend not built yet. Run `cd frontend && npm install && npm run build`.",
            }

    return app


app = create_app()
