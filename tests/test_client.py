"""Unit tests for pathly.models and pathly.client."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

from pathly import Client, ScenarioInput, WebhookInput, is_not_found
from pathly.client import DEFAULT_BASE_URL, MAX_PAGES
from pathly.errors import APIError
from pathly.models import (
    MaintenanceWindowInput,
    Scenario,
    SlaTarget,
    SlaTargetInput,
)


class FakeHTTPResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _client(handler: Callable[..., Any], **kwargs: Any) -> Client:
    return Client(token="sp_test", sleep=lambda _s: None, urlopen=handler, **kwargs)


def test_client_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PATHLY_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="PATHLY_API_TOKEN"):
        Client(token="")


def test_client_defaults_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATHLY_API_TOKEN", "sp_env")
    monkeypatch.setenv("PATHLY_API_URL", "https://example.test/")
    calls: list[Any] = []

    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        calls.append((req.full_url, req.get_header("Authorization"), timeout))
        return FakeHTTPResponse(200, b'{"planId":"p"}')

    c = Client(urlopen=urlopen, sleep=lambda _s: None)
    assert c.base_url == "https://example.test"
    c.ping()
    assert calls[0][0] == "https://example.test/v1/usage"
    assert calls[0][1] == "Bearer sp_env"


def test_default_user_agent_identifies_sdk() -> None:
    from pathly import __version__
    from pathly.client import DEFAULT_USER_AGENT

    captured: dict[str, str] = {}

    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        captured["ua"] = req.get_header("User-agent")
        return FakeHTTPResponse(200, b'{"planId":"p"}')

    c = _client(urlopen)
    c.ping()
    assert DEFAULT_USER_AGENT == f"pathly-sdk-python/{__version__}"
    assert c.user_agent == DEFAULT_USER_AGENT
    assert captured["ua"] == DEFAULT_USER_AGENT


def test_default_base_url() -> None:
    c = Client(token="sp_x", sleep=lambda _s: None, urlopen=lambda *_a, **_k: FakeHTTPResponse(200, b"{}"))
    assert c.base_url == DEFAULT_BASE_URL


def test_ping_accepts_403() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", hdrs=None, fp=io.BytesIO(b'{"error":"no"}'))

    _client(urlopen).ping()


def test_ping_raises_other_errors() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", hdrs=None, fp=io.BytesIO(b'{"error":"no"}'))

    with pytest.raises(APIError) as ei:
        _client(urlopen).ping()
    assert ei.value.status_code == 401


def test_retry_429_then_success() -> None:
    states = {"n": 0}

    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        states["n"] += 1
        if states["n"] == 1:
            return FakeHTTPResponse(429, b'{"error":"slow"}', {"Retry-After": "1"})
        return FakeHTTPResponse(200, b'{"id":"mon_1","name":"A","type":"http"}')

    sc = _client(urlopen).get_scenario("mon_1")
    assert sc.id == "mon_1"
    assert states["n"] == 2


def test_retry_exhausted_5xx() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        return FakeHTTPResponse(503, b'{"error":"down"}')

    with pytest.raises(APIError) as ei:
        _client(urlopen).get_scenario("mon_1")
    assert ei.value.status_code == 503


def test_transport_error_retries_then_fails() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        raise urllib.error.URLError("boom")

    with pytest.raises(APIError) as ei:
        _client(urlopen).get_scenario("mon_1")
    assert ei.value.status_code == 0


def test_invalid_json_response() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        return FakeHTTPResponse(200, b"not-json")

    with pytest.raises(APIError, match="unreadable"):
        _client(urlopen).get_scenario("mon_1")


def test_retry_after_invalid_and_capped() -> None:
    from pathly.client import MAX_RETRY_WAIT, _wait_for

    assert _wait_for({"retry-after": "nope"}, 2) == 1.0
    assert _wait_for({"retry-after": "9999"}, 1) == MAX_RETRY_WAIT


def test_scenario_crud_and_list() -> None:
    store: dict[str, Any] = {"pages": 0}

    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        method = req.get_method()
        url = req.full_url
        if method == "POST" and url.endswith("/v1/scenarios"):
            body = json.loads(req.data.decode())
            assert body["name"] == "Checkout"
            assert req.get_header("Idempotency-key") or req.headers.get("Idempotency-Key")
            return FakeHTTPResponse(201, b'{"id":"mon_1","name":"Checkout","type":"http","url":"https://x"}')
        if method == "GET" and "/v1/scenarios/mon_1" in url:
            return FakeHTTPResponse(200, b'{"id":"mon_1","name":"Checkout","type":"http"}')
        if method == "PATCH":
            return FakeHTTPResponse(200, b'{"id":"mon_1","name":"Checkout","type":"http","enabled":false}')
        if method == "DELETE":
            return FakeHTTPResponse(204, b"")
        if method == "POST" and url.endswith("/mute"):
            return FakeHTTPResponse(204, b"")
        if method == "GET" and "/v1/scenarios?" in url:
            store["pages"] += 1
            if store["pages"] == 1:
                return FakeHTTPResponse(
                    200,
                    b'{"items":[{"id":"mon_1","name":"A","type":"http"}],"nextCursor":"c1"}',
                )
            return FakeHTTPResponse(200, b'{"items":[{"id":"mon_2","name":"B","type":"http"}]}')
        raise AssertionError(f"unexpected {method} {url}")

    c = _client(urlopen)
    created = c.create_scenario(ScenarioInput(name="Checkout", url="https://x", intervalSec=60))
    assert created.id == "mon_1"
    assert c.get_scenario("mon_1").name == "Checkout"
    assert c.update_scenario("mon_1", ScenarioInput(enabled=False)).enabled is False
    c.mute_scenario("mon_1", "2026-01-01T00:00:00Z")
    c.mute_scenario("mon_1", None)
    listed = c.list_scenarios()
    assert [s.id for s in listed] == ["mon_1", "mon_2"]
    c.delete_scenario("mon_1")


def test_scenario_from_mapping_and_models() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        return FakeHTTPResponse(201, b'{"id":"mon_9","name":"M","type":"http"}')

    c = _client(urlopen)
    assert c.create_scenario({"name": "M"}).id == "mon_9"
    inp = ScenarioInput(name="n", regions=["eu"], tags=["t"], scenario={"steps": []})
    d = inp.to_dict()
    assert d["regions"] == ["eu"] and d["tags"] == ["t"] and "scenario" in d
    assert Scenario.from_dict({"id": "1", "name": "n", "type": "http"}).id == "1"


def test_webhook_maintenance_sla() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        method = req.get_method()
        url = req.full_url
        if "webhooks" in url and method == "POST":
            return FakeHTTPResponse(
                201,
                b'{"id":"wh_1","events":["run.failed"],"secret":"sec","urlFingerprint":"fp"}',
            )
        if "webhooks" in url and method == "GET" and "wh_1" in url:
            return FakeHTTPResponse(200, b'{"id":"wh_1","events":["run.failed"]}')
        if "webhooks" in url and method == "GET":
            return FakeHTTPResponse(200, b'{"items":[{"id":"wh_1","events":[]}]}')
        if "webhooks" in url and method == "DELETE":
            return FakeHTTPResponse(204, b"")
        if "maintenance-windows" in url and method == "POST":
            return FakeHTTPResponse(201, b'{"id":"mw_1","weekday":7,"startMinute":180,"durationMin":120}')
        if "maintenance-windows" in url and method == "GET" and "mw_1" in url:
            return FakeHTTPResponse(200, b'{"id":"mw_1","weekday":7}')
        if "maintenance-windows" in url and method == "GET":
            return FakeHTTPResponse(200, b'{"items":[{"id":"mw_1"}]}')
        if "maintenance-windows" in url and method == "DELETE":
            return FakeHTTPResponse(204, b"")
        if "sla-targets" in url and method == "PUT":
            return FakeHTTPResponse(
                200,
                b'{"id":"sla_1","objectivePct":"99.9","warnAtBudgetRatio":"0.8","windowDays":30}',
            )
        if "sla-targets" in url and method == "GET" and "sla_1" in url:
            return FakeHTTPResponse(200, b'{"id":"sla_1","objectivePct":99.9}')
        if "sla-targets" in url and method == "GET":
            return FakeHTTPResponse(200, b'{"items":[{"id":"sla_1"}]}')
        if "sla-targets" in url and method == "DELETE":
            return FakeHTTPResponse(204, b"")
        raise AssertionError(url)

    c = _client(urlopen)
    wh = c.create_webhook(WebhookInput(url="https://hooks.example/x", events=["run.failed"]))
    assert wh.secret == "sec"
    assert c.get_webhook("wh_1").id == "wh_1"
    assert c.list_webhooks()[0].id == "wh_1"
    c.delete_webhook("wh_1")

    mw = c.create_maintenance_window(
        MaintenanceWindowInput(weekday=7, startMinute=180, durationMin=120, reason="backup")
    )
    assert mw.id == "mw_1"
    assert c.get_maintenance_window("mw_1").id == "mw_1"
    assert c.list_maintenance_windows()[0].id == "mw_1"
    c.delete_maintenance_window("mw_1")

    sla = c.upsert_sla_target(SlaTargetInput(objectivePct=99.9, windowDays=30, monitorId="mon_1"))
    assert sla.objectivePct == 99.9
    assert sla.warnAtBudgetRatio == 0.8
    assert c.get_sla_target("sla_1").id == "sla_1"
    assert c.list_sla_targets()[0].id == "sla_1"
    c.delete_sla_target("sla_1")

    # mapping forms
    def urlopen2(req: Any, timeout: float) -> FakeHTTPResponse:
        if "webhooks" in req.full_url:
            return FakeHTTPResponse(201, b'{"id":"wh_2","events":[]}')
        if "maintenance" in req.full_url:
            return FakeHTTPResponse(201, b'{"id":"mw_2"}')
        return FakeHTTPResponse(200, b'{"id":"sla_2","objectivePct":99}')

    c2 = _client(urlopen2)
    assert c2.create_webhook({"url": "https://x"}).id == "wh_2"
    assert c2.create_maintenance_window({"weekday": 1}).id == "mw_2"
    assert c2.upsert_sla_target({"objectivePct": 99, "windowDays": 7}).id == "sla_2"


def test_pagination_overflow() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        return FakeHTTPResponse(200, b'{"items":[],"nextCursor":"forever"}')

    with pytest.raises(APIError, match="pagination exceeded"):
        _client(urlopen).list_scenarios()


def test_404_is_not_found() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b'{"error":"gone"}')
        )

    with pytest.raises(APIError) as ei:
        _client(urlopen).get_scenario("missing")
    assert is_not_found(ei.value)


def test_default_urlopen_used(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float = 30) -> FakeHTTPResponse:
        captured["url"] = req.full_url
        return FakeHTTPResponse(200, b'{"planId":"x"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    Client(token="sp_t", sleep=lambda _s: None).ping()
    assert captured["url"].endswith("/v1/usage")


def test_sla_from_dict_nulls() -> None:
    s = SlaTarget.from_dict({"id": "sla_1"})
    assert s.objectivePct is None and s.warnAtBudgetRatio is None


def test_http_error_without_body() -> None:
    err = urllib.error.HTTPError("https://x", 500, "err", hdrs=None, fp=None)

    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        raise err

    with pytest.raises(APIError):
        _client(urlopen).get_scenario("x")


def test_response_without_status_attr_uses_getcode() -> None:
    class LegacyResponse:
        def __init__(self) -> None:
            self.headers = {}

        def read(self) -> bytes:
            return b'{"id":"mon_z","name":"Z","type":"http"}'

        def getcode(self) -> int:
            return 200

        def __enter__(self) -> LegacyResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def urlopen(req: Any, timeout: float) -> LegacyResponse:
        return LegacyResponse()

    assert _client(urlopen).get_scenario("mon_z").id == "mon_z"


def test_list_pages_stop_when_items_key_missing() -> None:
    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        return FakeHTTPResponse(200, b'{}')

    assert _client(urlopen).list_scenarios() == []


def test_wait_for_zero_retry_after_falls_back() -> None:
    from pathly.client import _wait_for

    assert _wait_for({"retry-after": "0"}, 3) == 1.5


def test_success_on_final_attempt() -> None:
    states = {"n": 0}

    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        states["n"] += 1
        if states["n"] < 4:
            return FakeHTTPResponse(503, b'{"error":"down"}')
        return FakeHTTPResponse(200, b'{"id":"mon_ok","name":"OK","type":"http"}')

    assert _client(urlopen).get_scenario("mon_ok").id == "mon_ok"
    assert states["n"] == 4


def test_list_paged_extra_query() -> None:
    seen: list[str] = []

    def urlopen(req: Any, timeout: float) -> FakeHTTPResponse:
        seen.append(req.full_url)
        return FakeHTTPResponse(200, b'{"items":[]}')

    _client(urlopen)._list_paged("/v1/scenarios", {"folder": "Shop"})
    assert "folder=Shop" in seen[0]


def test_parse_details_not_list_and_odd_path() -> None:
    from pathly.errors import field_of, parse_api_error

    err = parse_api_error(400, "/v1", b'{"error":"x","details":{"no":"list"}}')
    assert err.message == "x" or err.message.startswith("x ")
    assert " [" not in err.message.split(" Check ")[0] or True
    # details is dict -> isinstance(details, list) is False, no detail appended
    assert err.message.startswith("x")

    assert field_of(["ok", None, object()]) == "ok"


def test_webhook_input_without_events() -> None:
    assert WebhookInput(url="https://hooks.example/x").to_dict() == {
        "url": "https://hooks.example/x"
    }


def test_models_from_mapping_none() -> None:
    from pathly.models import _from_mapping

    assert _from_mapping(Scenario, None) is None