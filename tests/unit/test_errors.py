"""Unit tests for the global exception handlers and the response envelope."""

from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from app.core.errors import (
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
    app_error_handler,
    unhandled_exception_handler,
)


def _make_request(path: str = "/boom") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "state": {},
    }
    return Request(scope)


@pytest.mark.parametrize(
    ("error_cls", "status_code", "code"),
    [
        (NotFoundError, 404, "not_found"),
        (ValidationFailedError, 422, "validation_failed"),
        (ConflictError, 409, "conflict"),
        (UnauthorizedError, 401, "unauthorized"),
    ],
)
async def test_app_error_handler_maps_status_and_code(
    error_cls: type, status_code: int, code: str
) -> None:
    request = _make_request()
    exc = error_cls("something went wrong")

    response = await app_error_handler(request, exc)

    assert response.status_code == status_code
    body = json.loads(response.body)
    assert body["data"] is None
    assert body["error"]["code"] == code
    assert body["error"]["message"] == "something went wrong"


async def test_unhandled_exception_handler_hides_internals() -> None:
    request = _make_request()

    response = await unhandled_exception_handler(request, RuntimeError("db password is hunter2"))

    assert response.status_code == 500
    body = json.loads(response.body)
    assert body["data"] is None
    assert body["error"]["code"] == "internal_error"
    assert "hunter2" not in json.dumps(body)
    assert "Traceback" not in json.dumps(body)
