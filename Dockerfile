# Base image note: this is glibc (Debian slim), not Alpine, on purpose. The
# platform's OpenTelemetry operator injects its Python auto-instrumentation via
# an init container built against glibc; on a musl base that injection fails at
# runtime. A smaller Alpine image would cost us the tracing the cluster is
# built around.
ARG PYTHON_VERSION=3.13

# ---------- build ----------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dependencies land in their own venv so the runtime stage copies one directory
# and inherits none of pip's build leftovers.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---------- runtime ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

# Pick up security fixes published since the base image was tagged; this is
# what keeps the Trivy CRITICAL/HIGH gate passing between base image releases.
RUN apt-get update \
 && apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    HOME=/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app ./app

# Build metadata, supplied by CI and surfaced on /api/info and app_build_info.
ARG APP_VERSION=0.0.0-dev
ARG GIT_SHA=unknown
ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA}

# OpenShift runs containers as an arbitrary UID in the root group, so anything
# the process reads or writes must be group-accessible rather than owned by a
# specific user.
RUN chgrp -R 0 /app /opt/venv \
 && chmod -R g=u /app /opt/venv

USER 1001

EXPOSE 8080

# No curl or wget in the slim image, and adding one would widen the scan
# surface — the interpreter we already ship can make the request.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).status==200 else 1)"]

CMD ["python", "-m", "app.main"]
