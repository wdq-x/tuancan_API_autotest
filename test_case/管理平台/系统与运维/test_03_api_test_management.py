# -*- coding: utf-8 -*-
"""Test-management platform and target execution API regression tests."""
import allure
import pytest

from config.project_information import default_headers
from utils.api_test_support import assert_auth_required, assert_client_error, assert_success, assert_validation_error, management_client
from utils.http_client import HttpClient


@pytest.fixture(scope="module")
def test_management_client():
    return management_client()


@allure.parent_suite("API regression")
@allure.suite("Management platform - test management")
class TestTestManagement:
    @allure.feature("Access control")
    def test_anonymous_scheduled_task_access_is_rejected(self):
        assert_auth_required(
            HttpClient(headers=default_headers.copy()).get("/v1/test-scheduled-tasks"),
            "anonymous scheduled task list",
        )

    @allure.feature("Environment and execution records")
    def test_test_management_read_models_are_available(self, test_management_client):
        environment_payload = assert_success(
            test_management_client.get("/v1/test-env-configs", params={"page": 1, "page_size": 10}),
            "list test environments",
        )
        assert environment_payload.get("data") is not None, environment_payload

        for path, params, action in (
            ("/v1/test-executions", {"page": 1, "page_size": 10}, "list test execution records"),
            ("/v1/test-scheduled-tasks", {"page": 1, "page_size": 10}, "list scheduled test tasks"),
        ):
            payload = assert_success(test_management_client.get(path, params=params), action)
            assert payload.get("data") is not None, payload

        environments = (environment_payload.get("data") or {}).get("items") or []
        if environments:
            environment_id = environments[0].get("id")
            payload = assert_success(
                test_management_client.get(
                    "/v1/test-execution/test-modules",
                    params={"env_config_id": environment_id, "test_type": "integration"},
                ),
                "list executable integration modules",
            )
            assert payload.get("data") is not None, payload

    @allure.feature("Validation")
    def test_test_environment_and_scheduled_task_require_valid_payloads(self, test_management_client):
        assert_validation_error(
            test_management_client.post("/v1/test-env-configs", json={}),
            "create empty test environment",
            (("body", "name"), ("body", "base_url")),
        )
        assert_validation_error(
            test_management_client.post("/v1/test-scheduled-tasks", json={}),
            "create empty scheduled test task",
            (("body", "task_name"), ("body", "env_config_id"), ("body", "schedule_type"), ("body", "schedule_config")),
        )


@allure.parent_suite("API regression")
@allure.suite("Management platform - test execution target")
class TestExecutionTargetCompatibility:
    @allure.feature("Target discovery")
    def test_target_test_module_discovery_is_available(self):
        payload = assert_success(
            HttpClient().get("/api/test-execution/test-modules", params={"test_type": "integration"}),
            "discover target test modules",
        )
        assert payload.get("data") is not None, payload

    @allure.feature("Target validation")
    def test_target_execution_rejects_an_empty_request(self):
        assert_client_error(
            HttpClient().post("/api/test-execution/execute", json={}),
            "execute target tests without a payload",
            code=1,
            msg="module_paths 必填",
            data_type=type(None),
        )
