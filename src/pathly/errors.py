"""HTTP and domain errors raised by the Pathly SDK."""

from __future__ import annotations

from typing import Any


class APIError(Exception):
    """Error returned by the Pathly API or the transport layer.

    The ``message`` is the API wording when available. Rewording it would hide
    the missing scope, the offending field, or the exceeded quota.
    """

    def __init__(self, status_code: int, message: str, path: str = "") -> None:
        self.status_code = status_code
        self.message = message
        self.path = path
        super().__init__(self.__str__())

    def __str__(self) -> str:
        if self.path:
            return f"{self.path}: {self.message} (HTTP {self.status_code})"
        return f"{self.message} (HTTP {self.status_code})"

    @property
    def is_not_found(self) -> bool:
        return self.status_code == 404


class NotFoundError(APIError):
    """Resource missing from the authenticated organization."""

    def __init__(self, message: str, path: str = "") -> None:
        super().__init__(404, message, path)


def is_not_found(err: BaseException) -> bool:
    """True when ``err`` reports a missing resource (HTTP 404)."""
    return isinstance(err, APIError) and err.is_not_found


def parse_api_error(status: int, path: str, body: bytes) -> APIError:
    """Build an :class:`APIError` from a raw response body."""
    text = body.decode("utf-8", errors="replace").strip()
    message = text or _status_text(status)
    try:
        import json

        parsed: dict[str, Any] = json.loads(text) if text else {}
    except (ValueError, TypeError):
        parsed = {}

    if isinstance(parsed, dict) and parsed.get("error"):
        message = str(parsed["error"])
        details = parsed.get("details") or []
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                field = field_of(detail.get("path") or [])
                detail_msg = detail.get("message") or ""
                message += f" [{field}: {detail_msg}]"

    if status == 401:
        message += (
            " Check PATHLY_API_TOKEN: an expired, revoked or truncated key "
            "gives the same response."
        )
    elif status == 403:
        message += (
            " Widen the scopes of the key, or check that the plan includes "
            "the feature."
        )

    if status == 404:
        return NotFoundError(message, path)
    return APIError(status, message, path)


def field_of(path: list[Any]) -> str:
    """Render a validation path as ``events.0``, or ``body`` when empty."""
    parts: list[str] = []
    for item in path:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, (int, float)):
            parts.append(str(int(item)))
    return ".".join(parts) if parts else "body"


def _status_text(status: int) -> str:
    from http import HTTPStatus

    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return f"HTTP {status}"
