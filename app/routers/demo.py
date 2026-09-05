"""Demo endpoints.

These exist to drive the platform's observability stack with traffic you
control: latency into the Mimir histograms, failures into the alert rules,
cross-service calls into Tempo, and log lines into Loki. Every parameter is
bounded so the controls cannot be turned into a way to take the pod down.
"""

import asyncio
import logging
import random
import time

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.state import state

router = APIRouter(prefix="/api", tags=["demo"])
log = logging.getLogger(__name__)

# Upper bounds keep a demo control from becoming a self-inflicted outage.
MAX_DELAY_MS = 10_000
MAX_BURN_MS = 2_000


class WorkResult(BaseModel):
    slept_ms: float
    burned_ms: float
    total_ms: float


class EchoResult(BaseModel):
    method: str
    path: str
    client: str | None
    headers: dict[str, str]
    trace_context: dict[str, str]


class DownstreamResult(BaseModel):
    url: str
    status_code: int
    elapsed_ms: float
    body: dict | None


class ReadyResult(BaseModel):
    ready: bool


def _burn_cpu(duration_ms: float) -> float:
    """Busy-loop for roughly `duration_ms`, returning what it actually took.

    Runs in a worker thread — spinning on the event loop would stall every
    other in-flight request and make the latency metrics meaningless.
    """
    deadline = time.perf_counter() + duration_ms / 1000
    start = time.perf_counter()
    while time.perf_counter() < deadline:
        pass
    return (time.perf_counter() - start) * 1000


@router.get("/work", response_model=WorkResult, summary="Simulate a slow request")
async def work(
    ms: int = Query(default=250, ge=0, le=MAX_DELAY_MS, description="Time spent awaiting I/O."),
    burn_ms: int = Query(default=0, ge=0, le=MAX_BURN_MS, description="Time spent burning CPU."),
    jitter: bool = Query(default=True, description="Vary the delay ±20% for realistic spreads."),
) -> WorkResult:
    """Spend a controlled amount of time, then return.

    `ms` models waiting on something external (it yields the event loop);
    `burn_ms` models real work. The split matters: only the second kind shows
    up as CPU pressure against the pod's limits.
    """
    delay = ms * random.uniform(0.8, 1.2) if jitter and ms else float(ms)  # noqa: S311

    started = time.perf_counter()
    if delay:
        await asyncio.sleep(delay / 1000)
    burned = await run_in_threadpool(_burn_cpu, burn_ms) if burn_ms else 0.0
    total = (time.perf_counter() - started) * 1000

    log.info(
        "handled synthetic work",
        extra={"slept_ms": round(delay, 2), "burned_ms": round(burned, 2)},
    )
    return WorkResult(
        slept_ms=round(delay, 2), burned_ms=round(burned, 2), total_ms=round(total, 2)
    )


@router.get("/error", summary="Return a deliberate error")
async def error(
    code: int = Query(default=500, ge=400, le=599, description="Status code to return."),
    message: str = Query(default="synthetic failure", max_length=200),
) -> None:
    """Fail on purpose, to exercise error-rate panels and alert rules."""
    log.warning("returning synthetic error", extra={"status_code": code})
    raise HTTPException(status_code=code, detail=message)


@router.get("/echo", response_model=EchoResult, summary="Echo the request")
async def echo(request: Request) -> EchoResult:
    """Show what actually arrived — useful for confirming that Traefik and the
    OTel SDK are propagating trace headers end to end.
    """
    headers = {k.lower(): v for k, v in request.headers.items()}
    trace_keys = ("traceparent", "tracestate", "baggage", "b3", "x-request-id")
    return EchoResult(
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else None,
        headers=headers,
        trace_context={k: headers[k] for k in trace_keys if k in headers},
    )


@router.get("/downstream", response_model=DownstreamResult, summary="Call a downstream service")
async def downstream(
    url: str | None = Query(default=None, description="Override the configured target."),
) -> DownstreamResult:
    """Make an outbound HTTP call so the trace has more than one span.

    The target defaults to the configured `downstream_url`; an override is
    accepted because it is how you demonstrate a CiliumNetworkPolicy denying
    egress to somewhere it shouldn't reach.
    """
    settings = get_settings()
    target = url or settings.downstream_url

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.downstream_timeout_seconds) as client:
            response = await client.get(target)
    except httpx.HTTPError as exc:
        log.exception("downstream call failed", extra={"target": target})
        raise HTTPException(status_code=502, detail=f"downstream call failed: {exc}") from exc

    elapsed = (time.perf_counter() - started) * 1000
    try:
        body = response.json()
    except ValueError:
        body = None

    return DownstreamResult(
        url=target,
        status_code=response.status_code,
        elapsed_ms=round(elapsed, 2),
        body=body if isinstance(body, dict) else None,
    )


@router.post("/ready", response_model=ReadyResult, summary="Toggle the readiness flag")
async def set_ready(ready: bool = Query(description="New readiness state.")) -> ReadyResult:
    """Flip /readyz for this pod only.

    Marking a pod unready removes it from the Service endpoints without killing
    it, which is how you show traffic draining to the remaining replicas. The
    flag is per-pod and in-memory, so a restart clears it.
    """
    state.ready = ready
    log.warning("readiness flag changed", extra={"ready": ready})
    return ReadyResult(ready=ready)
