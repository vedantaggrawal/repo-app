"""Prometheus instrumentation.

kube-prometheus-stack scrapes /metrics and remote-writes into Mimir. We use
prometheus-client directly rather than a wrapper library: it is one fewer
dependency to keep patched, and it lets us control label cardinality.

Cardinality note: the `path` label is the *route template*
(`/api/work`, not `/api/work?ms=250`), so a client hammering distinct URLs
cannot blow up the series count.
"""

import time
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)

LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
    # Tuned for a web app: sub-millisecond detail is noise, but we want
    # resolution either side of a 1s SLO.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being served.",
)

BUILD_INFO = Gauge(
    "app_build_info",
    "Build metadata; the value is always 1, the labels carry the information.",
    ["version", "git_sha", "environment"],
)


def _route_template(request: Request) -> str:
    """Templated path if the request matched a route, else a placeholder.

    Unmatched requests (404s) all collapse to `__unmatched__` — otherwise a
    scanner probing random URLs would create a new time series per URL.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or "__unmatched__"


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # /metrics itself is excluded: scraping should not inflate the counters
        # it is reporting.
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        IN_PROGRESS.inc()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            IN_PROGRESS.dec()
            # Resolved only after the route matched, so it is read here.
            path = _route_template(request)
            LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
            REQUESTS.labels(request.method, path, status).inc()


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
