"""Health, identity and metrics endpoints — the platform-facing surface."""

import platform

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.metrics import metrics_response
from app.state import state

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str


class Info(BaseModel):
    app: str
    version: str
    git_sha: str
    environment: str
    python: str
    pod: str
    node: str
    namespace: str
    uptime_seconds: float
    started_at_epoch: float


@router.get("/healthz", response_model=Health, summary="Liveness probe")
async def healthz() -> Health:
    """Liveness: is the process up at all?

    Never reports the readiness flag — a pod that is merely unready must not be
    restarted by the kubelet.
    """
    return Health(status="ok")


@router.get("/readyz", response_model=Health, summary="Readiness probe")
async def readyz(response: Response) -> Health:
    """Readiness: should this pod receive traffic?"""
    if not state.ready:
        response.status_code = 503
        return Health(status="not-ready")
    return Health(status="ready")


@router.get("/api/info", response_model=Info, summary="Build and pod identity")
async def info() -> Info:
    settings: Settings = get_settings()
    return Info(
        app=settings.app_name,
        version=settings.app_version,
        git_sha=settings.git_sha,
        environment=settings.environment,
        python=platform.python_version(),
        pod=settings.pod_name,
        node=settings.node_name,
        namespace=settings.namespace,
        uptime_seconds=state.uptime_seconds,
        started_at_epoch=state.started_at_epoch,
    )


@router.get("/metrics", include_in_schema=False, summary="Prometheus exposition")
async def metrics() -> Response:
    return metrics_response()
