import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core.config import settings
from backend.core.exceptions import AppException
from backend.core.logging import setup_logging
from backend.core.middleware import RequestIDMiddleware

logger = logging.getLogger(__name__)


def validate_security_settings() -> None:
    environment = settings.ENVIRONMENT.strip().lower()
    if environment in {"production", "prod"} and settings.JWT_SECRET == "change-me-to-a-random-string":
        raise RuntimeError("Refusing to start in production with the default JWT_SECRET")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    validate_security_settings()
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    if settings.JWT_SECRET == "change-me-to-a-random-string":
        logger.warning(
            "JWT_SECRET is using the default value. "
            "Set a strong secret via JWT_SECRET environment variable for production."
        )
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# ── Middleware ───────────────────────────────────────

cors_origins_raw = settings.CORS_ORIGINS.split(",") if settings.CORS_ORIGINS != "*" else ["*"]
cors_origins = [o.strip() for o in cors_origins_raw]
# CORS spec forbids credentials with wildcard origin
allow_credentials = "*" not in cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)


# ── Global exception handlers ────────────────────────

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=_http_status(exc.code),
        content={"code": exc.code, "data": None, "message": exc.message, "detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": 2001, "data": None, "message": "服务器内部错误", "detail": str(exc) if settings.DEBUG else None},
    )


def _http_status(code: int) -> int:
    _map = {1001: 400, 1002: 401, 1003: 403, 1004: 404, 1005: 429,
            2001: 500, 2002: 502, 2003: 503,
            3001: 400, 3002: 400, 3003: 400, 3004: 400}
    return _map.get(code, 500)


# ── Health check ─────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}


# ── Router includes ──────────────────────────────────
from backend.api.router_auth import router as auth_router
from backend.api.router_chat import router as chat_router
from backend.api.router_kb import router as kb_router
from backend.api.router_upload import router as upload_router
from backend.api.router_reports import router as reports_router
from backend.api.report_runs import router as report_runs_router
from backend.api.router_workflow import router as workflow_router
from backend.api.router_ws import router as ws_router

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(kb_router)
app.include_router(upload_router)
app.include_router(reports_router)
app.include_router(report_runs_router)
app.include_router(workflow_router)
app.include_router(ws_router)
