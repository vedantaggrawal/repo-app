"""Application entrypoint.

Note on tracing: there is deliberately no OpenTelemetry SDK code here. The
platform's OTel operator injects the SDK at admission when the pod carries

    instrumentation.opentelemetry.io/inject-python: "opentelemetry-operator/default"

so FastAPI, Starlette and httpx are instrumented without the app depending on
OTel at all. Adding the SDK here would double-instrument and pin us to a
version the operator also controls.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.logging import configure_logging
from app.metrics import BUILD_INFO, PrometheusMiddleware
from app.routers import demo, system

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    BUILD_INFO.labels(settings.app_version, settings.git_sha, settings.environment).set(1)
    log.info(
        "starting up",
        extra={
            "version": settings.app_version,
            "git_sha": settings.git_sha,
            "environment": settings.environment,
            "pod": settings.pod_name,
        },
    )
    yield
    log.info("shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="Platform demo console — drives the cluster's metrics, logs and traces.",
        lifespan=lifespan,
    )
    app.add_middleware(PrometheusMiddleware)
    app.include_router(system.router)
    app.include_router(demo.router)

    # The frontend. Mounted last so it cannot shadow an API route.
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def main() -> None:
    """Entrypoint used by the container. Single worker per pod — scale with
    replicas, which keeps the Prometheus registry per-process and correct."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level_number,
        access_log=True,
    )


if __name__ == "__main__":
    main()
