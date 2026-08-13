# -*- coding: utf-8 -*-
"""Shared helpers for management-platform API regression tests.

The helpers intentionally distinguish normal business failures from missing
permissions. A shared regression account may not have every optional module
permission, so a permission denial is reported as a skipped test instead of a
false product failure.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple, Type, Union

import pytest

from config.project_information import MANAGEMENT_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
INVALID_PARAMS_MESSAGE = "请求参数验证失败"
FORBIDDEN_CODE = 4030
TOKEN_INVALID_CODE = 5104
UNAUTHORIZED_CODE = 4010


def parse_json(response, action: str) -> Dict[str, Any]:
    """Return a JSON object with useful assertion output on protocol errors."""
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            "%s returned non-JSON: url=%s status=%s body=%s"
            % (action, response.url, response.status_code, response.text[:500])
        ) from exc
    assert isinstance(payload, dict), "%s response must be an object: %r" % (action, payload)
    return payload


def assert_success(response, action: str, permission_message: Optional[str] = None) -> Dict[str, Any]:
    """Assert the standard success envelope, skipping inaccessible modules."""
    assert response.status_code == 200, (
        "%s HTTP status is unexpected: url=%s status=%s body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = parse_json(response, action)
    if payload.get("code") == FORBIDDEN_CODE:
        pytest.skip(permission_message or "%s requires a permission not held by the test account" % action)
    assert payload.get("code") == SUCCESS_CODE, "%s business response is unsuccessful: %s" % (action, payload)
    assert "data" in payload, "%s success response lacks data: %s" % (action, payload)
    return payload


def assert_client_error(
    response,
    action: str,
    *,
    code: int,
    msg: str,
    data_type: Union[Type[Any], Tuple[Type[Any], ...]],
) -> Dict[str, Any]:
    """Assert one exact business-error contract.

    APIs in this project intentionally put business failures in a standard JSON
    envelope, often with HTTP 200. Callers must therefore state the expected
    code, message, and data shape. This prevents a generic ``5000``/``6001``
    response from accidentally satisfying an exception-path test.
    """
    assert 200 <= response.status_code < 500, (
        "%s returned a server error: url=%s status=%s body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = parse_json(response, action)
    assert set(("code", "msg", "data")).issubset(payload), (
        "%s error response lacks the standard envelope: %s" % (action, payload)
    )
    assert payload.get("code") == code, (
        "%s returned error code %r, expected %r: %s" % (action, payload.get("code"), code, payload)
    )
    assert payload.get("msg") == msg, (
        "%s returned error message %r, expected %r: %s" % (action, payload.get("msg"), msg, payload)
    )
    assert isinstance(payload.get("data"), data_type), (
        "%s returned error data %r, expected %s: %s"
        % (action, payload.get("data"), data_type, payload)
    )
    return payload


def assert_validation_error(
    response,
    action: str,
    expected_locations: Sequence[Tuple[str, str]],
) -> Dict[str, Any]:
    """Assert the framework validation envelope and its rejected fields."""
    payload = assert_client_error(
        response,
        action,
        code=INVALID_PARAMS_CODE,
        msg=INVALID_PARAMS_MESSAGE,
        data_type=list,
    )
    locations = {
        tuple(item.get("loc") or ())
        for item in payload["data"]
        if isinstance(item, dict)
    }
    for location in expected_locations:
        assert location in locations, (
            "%s lacks validation detail for %s: %s" % (action, location, payload)
        )
    return payload


def assert_auth_required(response, action: str) -> None:
    """Verify that an anonymous request does not gain protected access."""
    assert 200 <= response.status_code < 500, (
        "%s returned a server error: status=%s body=%s" % (action, response.status_code, response.text[:500])
    )
    if response.status_code in (401, 403):
        return
    payload = parse_json(response, action)
    assert payload.get("code") in {TOKEN_INVALID_CODE, UNAUTHORIZED_CODE, FORBIDDEN_CODE}, (
        "%s unexpectedly allowed anonymous access: %s" % (action, payload)
    )


def management_client(client_type: str = "pc") -> HttpClient:
    """Log in with the configured management-platform account."""
    account = MANAGEMENT_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("MANAGEMENT_TEST_USERNAME / MANAGEMENT_TEST_PASSWORD is not configured")

    client = HttpClient(headers=default_headers.copy())
    payload = assert_success(
        client.post("/v1/login", json={"username": username, "password": password, "client_type": client_type}),
        "log in to the management platform",
    )
    token = (payload.get("data") or {}).get("access_token")
    assert token, "login succeeded but access_token is missing: %s" % payload
    client.headers["Authorization"] = "Bearer %s" % token
    return client


def page_items(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Return list items from either a paging envelope or a direct list."""
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    return []


def first_id(payload: Dict[str, Any], keys: Iterable[str] = ("id",)) -> Optional[int]:
    """Find the first positive integer identifier in common list envelopes."""
    for item in page_items(payload):
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = item.get(key)
            if isinstance(value, int) and value > 0:
                return value
    return None
