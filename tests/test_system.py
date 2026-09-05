"""Tests for the platform-facing surface: probes, identity, metrics."""

import logging

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_healthz_is_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_is_ready_by_default(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_reports_503_when_flag_is_cleared(client):
    client.post("/api/ready", params={"ready": False})

    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not-ready"


def test_liveness_stays_ok_while_unready(client):
    """An unready pod must not be restarted by the kubelet."""
    client.post("/api/ready", params={"ready": False})

    assert client.get("/healthz").status_code == 200


def test_info_reports_build_and_pod_identity(client):
    body = client.get("/api/info").json()

    assert body["app"] == "devops-test-webserver"
    assert body["environment"] == "local"
    assert body["python"].startswith("3.")
    assert body["uptime_seconds"] >= 0
    for field in ("version", "git_sha", "pod", "node", "namespace"):
        assert body[field], f"{field} should not be empty"


def test_metrics_exposes_prometheus_text(client):
    client.get("/healthz")

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

    body = response.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert "app_build_info" in body


def test_metrics_labels_use_the_route_template_not_the_raw_path(client):
    """Unbounded query strings must not create one time series per URL."""
    client.get("/api/work", params={"ms": 0, "jitter": False})

    body = client.get("/metrics").text
    assert 'path="/api/work"' in body
    assert "ms=0" not in body


def test_unmatched_routes_collapse_to_one_series(client):
    client.get("/nope-one")
    client.get("/nope-two")

    body = client.get("/metrics").text
    assert 'path="__unmatched__"' in body
    assert "nope-one" not in body


def test_index_serves_the_frontend(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Platform Demo Console" in response.text


def test_static_assets_are_served(client):
    assert client.get("/assets/app.css").status_code == 200
    assert client.get("/assets/app.js").status_code == 200


class TestLogLevelNormalization:
    """`LOG_LEVEL=warn` is what the prod values file sets. Python's logging
    accepts WARN as an alias; uvicorn does not, and passing it through crashed
    the process at startup before it served anything."""

    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            ("warn", "WARNING"),
            ("WARN", "WARNING"),
            ("  warn  ", "WARNING"),
            ("fatal", "CRITICAL"),
            ("trace", "DEBUG"),
            ("debug", "DEBUG"),
            ("info", "INFO"),
            ("WARNING", "WARNING"),
        ],
    )
    def test_aliases_and_case_are_normalized(self, monkeypatch, configured, expected):
        monkeypatch.setenv("LOG_LEVEL", configured)

        assert Settings().log_level == expected

    def test_numeric_level_is_what_uvicorn_receives(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "warn")

        # uvicorn rejects the string "warn" but accepts the int.
        assert Settings().log_level_number == logging.WARNING

    def test_unknown_level_is_rejected_with_a_useful_message(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "verbose")

        with pytest.raises(ValidationError, match="unknown log level"):
            Settings()

    def test_default_is_info(self):
        assert Settings().log_level == "INFO"
