"""Tests for the demo endpoints, including the bounds that keep them safe."""

import httpx
import pytest


def test_work_sleeps_for_roughly_the_requested_time(client):
    body = client.get("/api/work", params={"ms": 120, "jitter": False}).json()

    assert body["slept_ms"] == pytest.approx(120, abs=1)
    assert body["total_ms"] >= 100


def test_work_jitter_stays_within_twenty_percent(client):
    for _ in range(15):
        slept = client.get("/api/work", params={"ms": 100, "jitter": True}).json()["slept_ms"]
        assert 80 <= slept <= 120


def test_work_burns_cpu_when_asked(client):
    body = client.get("/api/work", params={"ms": 0, "burn_ms": 60}).json()

    assert body["burned_ms"] >= 55
    assert body["slept_ms"] == 0


def test_work_rejects_a_delay_beyond_the_cap(client):
    """The bound is what stops a demo control being a self-inflicted outage."""
    assert client.get("/api/work", params={"ms": 60_000}).status_code == 422


def test_work_rejects_a_burn_beyond_the_cap(client):
    assert client.get("/api/work", params={"burn_ms": 30_000}).status_code == 422


@pytest.mark.parametrize("code", [400, 404, 429, 500, 503])
def test_error_returns_the_requested_status(client, code):
    response = client.get("/api/error", params={"code": code})

    assert response.status_code == code
    assert response.json()["detail"] == "synthetic failure"


def test_error_rejects_a_non_error_status(client):
    assert client.get("/api/error", params={"code": 200}).status_code == 422


def test_echo_surfaces_trace_context_headers(client):
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    body = client.get("/api/echo", headers={"traceparent": traceparent, "b3": "abc"}).json()

    assert body["method"] == "GET"
    assert body["path"] == "/api/echo"
    assert body["trace_context"]["traceparent"] == traceparent
    assert body["trace_context"]["b3"] == "abc"


def test_echo_omits_headers_that_were_not_sent(client):
    body = client.get("/api/echo").json()

    assert "traceparent" not in body["trace_context"]


def test_downstream_returns_the_target_response(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"app": "downstream"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    body = client.get("/api/downstream", params={"url": "http://svc/api/info"}).json()

    assert body["url"] == "http://svc/api/info"
    assert body["status_code"] == 200
    assert body["body"] == {"app": "downstream"}
    assert body["elapsed_ms"] >= 0


def test_downstream_maps_a_transport_failure_to_502(client, monkeypatch):
    """A blocked egress path should read as a bad gateway, not a crash."""

    async def fail(self, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail)

    response = client.get("/api/downstream")

    assert response.status_code == 502
    assert "downstream call failed" in response.json()["detail"]


def test_downstream_tolerates_a_non_json_body(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, text="plain text", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    body = client.get("/api/downstream").json()

    assert body["status_code"] == 200
    assert body["body"] is None


def test_ready_toggles_both_ways(client):
    assert client.post("/api/ready", params={"ready": False}).json() == {"ready": False}
    assert client.get("/readyz").status_code == 503

    assert client.post("/api/ready", params={"ready": True}).json() == {"ready": True}
    assert client.get("/readyz").status_code == 200
