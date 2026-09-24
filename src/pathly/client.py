"""HTTP client for the Pathly public ``/v1`` API.

Hand-written (not generated) so creates stay idempotent, ``Retry-After`` is
honoured, and a missing resource (404) is distinct from a transport failure.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping, Optional, Sequence
from uuid import uuid4

from pathly._version import __version__
from pathly.errors import APIError, parse_api_error
from pathly.models import (
    MaintenanceWindow,
    MaintenanceWindowInput,
    Scenario,
    ScenarioInput,
    SlaTarget,
    SlaTargetInput,
    Webhook,
    WebhookInput,
)

DEFAULT_BASE_URL = "https://api.pathlyhq.com"
DEFAULT_USER_AGENT = f"pathly-sdk-python/{__version__}"
MAX_ATTEMPTS = 4
MAX_RETRY_WAIT = 90.0
PAGE_SIZE = 200
MAX_PAGES = 200

SleepFn = Callable[[float], None]
OpenerFn = Callable[[urllib.request.Request, float], Any]


class Client:
    """Thread-safe client. The token is never logged."""

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        timeout: float = 30.0,
        user_agent: Optional[str] = None,
        sleep: SleepFn = time.sleep,
        urlopen: Optional[OpenerFn] = None,
    ) -> None:
        resolved = (token if token is not None else os.environ.get("PATHLY_API_TOKEN", "")).strip()
        if not resolved:
            raise ValueError(
                "PATHLY_API_TOKEN is required. Export it, or pass token= to Client()."
            )
        url = (base_url if base_url is not None else os.environ.get("PATHLY_API_URL", "")).strip()
        if not url:
            url = DEFAULT_BASE_URL
        self.base_url = url.rstrip("/")
        self._token = resolved
        self.timeout = timeout
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self._sleep = sleep
        self._urlopen = urlopen or self._default_urlopen

    @staticmethod
    def _default_urlopen(request: urllib.request.Request, timeout: float) -> Any:
        return urllib.request.urlopen(request, timeout=timeout)

    # ------------------------------------------------------------------ HTTP
    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        idempotency_key: Optional[str] = None,
        expect_json: bool = True,
    ) -> Any:
        payload: Optional[bytes] = None
        if body is not None:
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")

        last_error: Optional[BaseException] = None
        for attempt in range(1, MAX_ATTEMPTS):
            wait, result, err = self._attempt(
                method, path, payload, idempotency_key, expect_json, attempt, last=False
            )
            if wait <= 0:
                if err is not None:
                    raise err
                return result
            last_error = err
            self._sleep(wait)

        _, result, err = self._attempt(
            method, path, payload, idempotency_key, expect_json, MAX_ATTEMPTS, last=True
        )
        if err is not None:
            raise err
        return result

    def _attempt(
        self,
        method: str,
        path: str,
        payload: Optional[bytes],
        idempotency_key: Optional[str],
        expect_json: bool,
        attempt: int,
        *,
        last: bool,
    ) -> tuple[float, Any, Optional[BaseException]]:
        req = urllib.request.Request(self.base_url + path, data=payload, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", self.user_agent)
        if payload is not None:
            req.add_header("Content-Type", "application/json")
        if idempotency_key:
            req.add_header("Idempotency-Key", idempotency_key)

        try:
            with self._urlopen(req, self.timeout) as res:
                status = getattr(res, "status", None) or res.getcode()
                raw = res.read()
                headers = {k.lower(): v for k, v in res.headers.items()}
        except urllib.error.HTTPError as exc:
            raw = exc.read() if exc.fp is not None else b""
            status = exc.code
            headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        except urllib.error.URLError as exc:
            wrapped = APIError(0, f"calling {method} {path}: {exc.reason}", path)
            if last:
                return 0.0, None, wrapped
            return _backoff(attempt), None, wrapped

        if status == 429 or status >= 500:
            failure = parse_api_error(status, path, raw)
            if last:
                return 0.0, None, failure
            return _wait_for(headers, attempt), None, failure

        if status >= 400:
            return 0.0, None, parse_api_error(status, path, raw)

        if not expect_json or not raw:
            return 0.0, None, None
        try:
            return 0.0, json.loads(raw.decode("utf-8")), None
        except (ValueError, UnicodeDecodeError) as exc:
            return 0.0, None, APIError(
                status,
                f"unreadable response from {method} {path}: {exc}",
                path,
            )

    def ping(self) -> None:
        """Verify the token. A 403 is accepted (key valid, missing ``org:read``)."""
        try:
            self.request("GET", "/v1/usage")
        except APIError as err:
            if err.status_code == 403:
                return
            raise

    # -------------------------------------------------------------- Scenarios
    def create_scenario(
        self, data: ScenarioInput | Mapping[str, Any], *, idempotency_key: Optional[str] = None
    ) -> Scenario:
        body = data.to_dict() if isinstance(data, ScenarioInput) else dict(data)
        out = self.request(
            "POST",
            "/v1/scenarios",
            body=body,
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return Scenario.from_dict(out)

    def get_scenario(self, scenario_id: str) -> Scenario:
        out = self.request("GET", f"/v1/scenarios/{_esc(scenario_id)}")
        return Scenario.from_dict(out)

    def update_scenario(
        self, scenario_id: str, data: ScenarioInput | Mapping[str, Any]
    ) -> Scenario:
        body = data.to_dict() if isinstance(data, ScenarioInput) else dict(data)
        out = self.request("PATCH", f"/v1/scenarios/{_esc(scenario_id)}", body=body)
        return Scenario.from_dict(out)

    def delete_scenario(self, scenario_id: str) -> None:
        self.request("DELETE", f"/v1/scenarios/{_esc(scenario_id)}", expect_json=False)

    def list_scenarios(self) -> list[Scenario]:
        return [
            Scenario.from_dict(item)
            for item in self._list_paged("/v1/scenarios")
        ]

    def mute_scenario(self, scenario_id: str, muted_until: Optional[str] = None) -> None:
        self.request(
            "POST",
            f"/v1/scenarios/{_esc(scenario_id)}/mute",
            body={"mutedUntil": muted_until},
            expect_json=False,
        )

    # ---------------------------------------------------- Maintenance windows
    def create_maintenance_window(
        self,
        data: MaintenanceWindowInput | Mapping[str, Any],
        *,
        idempotency_key: Optional[str] = None,
    ) -> MaintenanceWindow:
        body = data.to_dict() if isinstance(data, MaintenanceWindowInput) else dict(data)
        out = self.request(
            "POST",
            "/v1/maintenance-windows",
            body=body,
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return MaintenanceWindow.from_dict(out)

    def get_maintenance_window(self, window_id: str) -> MaintenanceWindow:
        out = self.request("GET", f"/v1/maintenance-windows/{_esc(window_id)}")
        return MaintenanceWindow.from_dict(out)

    def delete_maintenance_window(self, window_id: str) -> None:
        self.request(
            "DELETE",
            f"/v1/maintenance-windows/{_esc(window_id)}",
            expect_json=False,
        )

    def list_maintenance_windows(self) -> list[MaintenanceWindow]:
        return [
            MaintenanceWindow.from_dict(item)
            for item in self._list_paged("/v1/maintenance-windows")
        ]

    # --------------------------------------------------------------- Webhooks
    def create_webhook(
        self, data: WebhookInput | Mapping[str, Any], *, idempotency_key: Optional[str] = None
    ) -> Webhook:
        body = data.to_dict() if isinstance(data, WebhookInput) else dict(data)
        out = self.request(
            "POST",
            "/v1/webhooks",
            body=body,
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return Webhook.from_dict(out)

    def get_webhook(self, webhook_id: str) -> Webhook:
        out = self.request("GET", f"/v1/webhooks/{_esc(webhook_id)}")
        return Webhook.from_dict(out)

    def delete_webhook(self, webhook_id: str) -> None:
        self.request("DELETE", f"/v1/webhooks/{_esc(webhook_id)}", expect_json=False)

    def list_webhooks(self) -> list[Webhook]:
        return [Webhook.from_dict(item) for item in self._list_paged("/v1/webhooks")]

    # ------------------------------------------------------------ SLA targets
    def upsert_sla_target(
        self, data: SlaTargetInput | Mapping[str, Any], *, idempotency_key: Optional[str] = None
    ) -> SlaTarget:
        body = data.to_dict() if isinstance(data, SlaTargetInput) else dict(data)
        out = self.request(
            "PUT",
            "/v1/sla-targets",
            body=body,
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return SlaTarget.from_dict(out)

    def get_sla_target(self, target_id: str) -> SlaTarget:
        out = self.request("GET", f"/v1/sla-targets/{_esc(target_id)}")
        return SlaTarget.from_dict(out)

    def delete_sla_target(self, target_id: str) -> None:
        self.request("DELETE", f"/v1/sla-targets/{_esc(target_id)}", expect_json=False)

    def list_sla_targets(self) -> list[SlaTarget]:
        return [SlaTarget.from_dict(item) for item in self._list_paged("/v1/sla-targets")]

    # -------------------------------------------------------------- Pagination
    def _list_paged(self, base: str, extra: Optional[Mapping[str, str]] = None) -> list[dict]:
        items: list[dict] = []
        cursor = ""
        for _ in range(MAX_PAGES):
            query: dict[str, str] = {"limit": str(PAGE_SIZE)}
            if extra:
                query.update(extra)
            if cursor:
                query["cursor"] = cursor
            path = f"{base}?{urllib.parse.urlencode(query)}"
            page = self.request("GET", path)
            batch = page.get("items") or []
            items.extend(batch)
            next_cursor = page.get("nextCursor")
            if not next_cursor:
                return items
            cursor = str(next_cursor)
        raise APIError(0, f"pagination exceeded {MAX_PAGES} pages for {base}", base)


def _esc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _backoff(attempt: int) -> float:
    return float(attempt) * 0.5


def _wait_for(headers: Mapping[str, str], attempt: int) -> float:
    raw = headers.get("retry-after", "")
    if raw:
        try:
            secs = float(str(raw).strip())
            if secs > 0:
                return min(secs, MAX_RETRY_WAIT)
        except ValueError:
            pass
    return _backoff(attempt)
