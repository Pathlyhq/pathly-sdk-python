"""Unit tests for pathly.errors."""

from __future__ import annotations

from pathly.errors import APIError, NotFoundError, field_of, is_not_found, parse_api_error


def test_api_error_str_with_and_without_path() -> None:
    assert str(APIError(400, "bad", "/v1/x")) == "/v1/x: bad (HTTP 400)"
    assert str(APIError(400, "bad")) == "bad (HTTP 400)"


def test_is_not_found() -> None:
    assert is_not_found(NotFoundError("gone", "/v1/x"))
    assert not is_not_found(APIError(400, "bad"))
    assert not is_not_found(ValueError("nope"))
    assert APIError(404, "x").is_not_found


def test_parse_api_error_plain_and_json() -> None:
    err = parse_api_error(400, "/v1/s", b"plain")
    assert err.message == "plain"
    assert err.status_code == 400

    err = parse_api_error(
        422,
        "/v1/s",
        b'{"error":"Invalid","details":[{"path":["events",0],"message":"bad"}]}',
    )
    assert "Invalid" in err.message
    assert "events.0" in err.message

    err = parse_api_error(422, "/v1/s", b'{"error":"x","details":["skip"]}')
    assert "x" in err.message

    err = parse_api_error(400, "/v1/s", b"{")
    assert err.message == "{"

    err = parse_api_error(418, "/v1/s", b"")
    assert "teapot" in err.message.lower()

    err = parse_api_error(599, "/v1/s", b"")
    assert "599" in err.message

    err = parse_api_error(
        422,
        "/v1/s",
        b'{"error":"x","details":[{"path":[],"message":"whole"}]}',
    )
    assert "body" in err.message


def test_parse_auth_hints() -> None:
    assert "PATHLY_API_TOKEN" in parse_api_error(401, "/v1", b'{"error":"no"}').message
    assert "scopes" in parse_api_error(403, "/v1", b'{"error":"no"}').message
    assert isinstance(parse_api_error(404, "/v1", b'{"error":"gone"}'), NotFoundError)


def test_field_of() -> None:
    assert field_of([]) == "body"
    assert field_of(["a", 1, 2.0]) == "a.1.2"
