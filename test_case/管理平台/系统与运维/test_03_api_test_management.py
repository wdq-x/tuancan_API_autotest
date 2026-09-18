# -*- coding: utf-8 -*-
"""Test-management platform and target execution API regression tests."""
import time
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, default_headers
from utils.api_test_support import (
    assert_auth_required,
    assert_client_error,
    assert_success,
    assert_validation_error,
    management_client,
    parse_json,
)
from utils.http_client import HttpClient


@pytest.fixture(scope="module")
def test_management_client():
    return management_client()


def _require_write_tests():
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _create_temporary_environment(client):
    payload = assert_success(
        client.post(
            "/v1/test-env-configs",
            json={
                "name": "AT-测试环境-%s" % uuid4().hex[:12],
                "base_url": "http://127.0.0.1:7777",
                "is_active": True,
                "sort_order": 99,
            },
        ),
        "create temporary test environment",
    )
    environment = payload["data"]
    assert isinstance(environment, dict), environment
    assert isinstance(environment.get("id"), int) and environment["id"] > 0, environment
    assert environment["base_url"] == "http://127.0.0.1:7777", environment
    return environment


def _cleanup_environment(client, environment_id):
    if not environment_id:
        return
    try:
        client.delete("/v1/test-env-configs/%s" % environment_id)
    except Exception:
        pass


def _assert_target_error(response, action, expected_status, expected_code):
    assert response.status_code == expected_status, "%s HTTP 状态异常：%s" % (action, response.text)
    payload = parse_json(response, action)
    assert payload.get("code") == expected_code, "%s 业务码不正确：%s" % (action, payload)
    return payload


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与运维-测试管理")
class Test测试管理:
    @allure.feature("访问控制")
    @allure.title("未登录访问定时测试任务被拒绝")
    @allure.step("执行：未登录访问定时测试任务被拒绝")
    def test_anonymous_scheduled_task_access_is_rejected(self):
        assert_auth_required(
            HttpClient(headers=default_headers.copy()).get("/v1/test-scheduled-tasks"),
            "anonymous scheduled task list",
        )

    @allure.feature("环境与执行记录")
    @allure.title("测试环境定时任务与执行记录查询")
    @allure.step("执行：测试环境定时任务与执行记录查询")
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

    @allure.feature("参数校验")
    @allure.title("测试环境与定时任务创建参数校验")
    @allure.step("执行：测试环境与定时任务创建参数校验")
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


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与运维-测试管理")
class Test测试管理生命周期:
    @allure.feature("环境配置与定时任务")
    @allure.title("测试环境与定时任务创建编辑启停删除")
    @allure.step("执行：测试环境与定时任务创建编辑启停删除")
    def test_test_environment_and_scheduled_task_lifecycle(self, test_management_client):
        _require_write_tests()
        environment_id = None
        task_id = None
        try:
            environment = _create_temporary_environment(test_management_client)
            environment_id = environment["id"]

            updated_environment_payload = assert_success(
                test_management_client.put(
                    "/v1/test-env-configs/%s" % environment_id,
                    json={
                        "name": "AT-测试环境已更新-%s" % uuid4().hex[:10],
                        "is_active": False,
                        "sort_order": 100,
                    },
                ),
                "update temporary test environment",
            )
            updated_environment = updated_environment_payload["data"]
            assert updated_environment["id"] == environment_id, updated_environment
            assert updated_environment["is_active"] is False, updated_environment
            assert updated_environment["sort_order"] == 100, updated_environment

            detail_payload = assert_success(
                test_management_client.get("/v1/test-env-configs/%s" % environment_id),
                "get temporary test environment",
            )
            assert detail_payload["data"]["id"] == environment_id, detail_payload

            task_payload = assert_success(
                test_management_client.post(
                    "/v1/test-scheduled-tasks",
                    json={
                        "task_name": "AT-定时任务-%s" % uuid4().hex[:12],
                        "env_config_id": environment_id,
                        "test_type": "integration",
                        "module_paths": ["test_case/管理平台/系统与运维/test_03_api_test_management.py"],
                        "schedule_type": "interval",
                        "schedule_config": {"minutes": 30},
                        "enabled": True,
                    },
                ),
                "create temporary scheduled task",
            )
            task = task_payload["data"]
            task_id = task["id"]
            assert task["env_config_id"] == environment_id, task
            assert task["schedule_type"] == "interval", task
            assert task["schedule_config"] == {"minutes": 30}, task
            assert task["enabled"] is True, task

            updated_task_payload = assert_success(
                test_management_client.put(
                    "/v1/test-scheduled-tasks/%s" % task_id,
                    json={
                        "task_name": "AT-定时任务已更新-%s" % uuid4().hex[:10],
                        "enabled": False,
                        "schedule_config": {"minutes": 45},
                    },
                ),
                "update temporary scheduled task",
            )
            updated_task = updated_task_payload["data"]
            assert updated_task["id"] == task_id, updated_task
            assert updated_task["enabled"] is False, updated_task
            assert updated_task["schedule_config"] == {"minutes": 45}, updated_task

            enable_payload = assert_success(
                test_management_client.post(
                    "/v1/test-scheduled-tasks/%s/toggle" % task_id,
                    json={"enabled": True},
                ),
                "enable temporary scheduled task",
            )
            assert enable_payload["data"] == {"enabled": True}, enable_payload

            task_detail_payload = assert_success(
                test_management_client.get("/v1/test-scheduled-tasks/%s" % task_id),
                "get temporary scheduled task",
            )
            assert task_detail_payload["data"]["enabled"] is True, task_detail_payload

            assert_success(
                test_management_client.delete("/v1/test-scheduled-tasks/%s" % task_id),
                "delete temporary scheduled task",
            )
            task_id = None
            deleted_task_response = test_management_client.get("/v1/test-scheduled-tasks/%s" % task["id"])
            assert_client_error(
                deleted_task_response,
                "get deleted scheduled task",
                code=4040,
                msg="定时任务不存在",
                data_type=(dict, list, type(None)),
            )
        finally:
            if task_id:
                try:
                    test_management_client.delete("/v1/test-scheduled-tasks/%s" % task_id)
                except Exception:
                    pass
            _cleanup_environment(test_management_client, environment_id)

    @allure.feature("自环模块发现")
    @allure.title("本机测试环境模块发现按测试类型返回")
    @allure.step("执行：本机测试环境模块发现按测试类型返回")
    def test_local_test_module_discovery_returns_requested_type(self, test_management_client):
        _require_write_tests()
        environment_id = None
        try:
            environment = _create_temporary_environment(test_management_client)
            environment_id = environment["id"]
            payload = assert_success(
                test_management_client.get(
                    "/v1/test-execution/test-modules",
                    params={"env_config_id": environment_id, "test_type": "integration"},
                ),
                "discover local integration test modules",
            )
            data = payload["data"]
            assert set(data) == {"integration"}, data
            assert isinstance(data["integration"], list), data
        finally:
            _cleanup_environment(test_management_client, environment_id)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与运维-测试管理")
class Test测试执行边界:
    @allure.feature("路由暴露")
    @allure.title("目标执行路由由 API 服务接管")
    @allure.step("执行：目标执行路由由 API 服务接管")
    def test_target_execution_api_routes_are_exposed(self):
        response = HttpClient(headers=default_headers.copy()).get(
            "/v1/api/test-execution/test-modules",
            params={"test_type": "integration"},
        )
        assert response.status_code == 200, response.text
        payload = parse_json(response, "check target execution API route")
        assert payload.get("code") == 20000, payload
        assert isinstance(payload.get("data"), dict), payload

    @allure.feature("目标执行参数")
    @allure.title("目标执行接口拒绝空模块和非法测试类型")
    @allure.step("执行：目标执行接口拒绝空模块和非法测试类型")
    def test_target_execution_rejects_missing_modules_and_invalid_type(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        missing_modules = anonymous_client.post("/v1/api/test-execution/execute", json={})
        _assert_target_error(missing_modules, "target execution missing module_paths", 400, 1)

        invalid_type = anonymous_client.post(
            "/v1/api/test-execution/execute",
            json={"module_paths": ["test_case"], "test_type": "invalid"},
        )
        _assert_target_error(invalid_type, "target execution invalid test_type", 400, 1)

    @allure.feature("执行状态")
    @allure.title("目标执行不存在路径进入错误态并可查询状态")
    @allure.step("执行：目标执行不存在路径进入错误态并可查询状态")
    def test_target_execution_missing_path_becomes_error(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        start_response = anonymous_client.post(
            "/v1/api/test-execution/execute",
            json={
                "domain_name": "AT-不存在路径",
                "base_url": "http://127.0.0.1:7777",
                "module_paths": ["test_case/AT-不存在的测试文件.py"],
                "test_type": "integration",
            },
        )
        start_payload = assert_success(start_response, "start target execution with missing path")
        execution_id = start_payload["data"]["execution_id"]
        assert start_payload["data"]["status"] == "running", start_payload

        for _ in range(10):
            status_response = anonymous_client.get(
                "/v1/api/test-execution/%s/status" % execution_id
            )
            status_payload = assert_success(status_response, "get target execution status")
            if status_payload["data"]["status"] != "running":
                break
            time.sleep(0.2)

        status_data = status_payload["data"]
        assert status_data["status"] == "error", status_data
        assert status_data["error_message"] == "测试路径不存在", status_data
        assert status_data["total_tests"] == 0, status_data

    @allure.feature("执行状态")
    @allure.title("目标执行未知记录返回不存在")
    @allure.step("执行：目标执行未知记录返回不存在")
    def test_target_execution_unknown_record_returns_not_found(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        status_response = anonymous_client.get("/v1/api/test-execution/2147483647/status")
        _assert_target_error(status_response, "get unknown target execution status", 404, 1)

        stop_response = anonymous_client.post("/v1/api/test-execution/2147483647/stop")
        assert stop_response.status_code in (400, 404), stop_response.text
        stop_payload = parse_json(stop_response, "stop unknown target execution")
        assert stop_payload.get("code") != 20000, stop_payload

    @allure.feature("代理和报告")
    @allure.title("执行代理和报告详情拒绝未知资源")
    @allure.step("执行：执行代理和报告详情拒绝未知资源")
    def test_execution_proxy_and_report_detail_reject_unknown_resources(self, test_management_client):
        proxy_response = test_management_client.get(
            "/v1/test-execution/proxy/2147483647/1/status"
        )
        assert_client_error(
            proxy_response,
            "proxy unknown environment",
            code=4040,
            msg="环境配置不存在",
            data_type=(dict, list, type(None)),
        )

        detail_response = test_management_client.get(
            "/v1/test-execution/2147483647/report-detail"
        )
        assert_client_error(
            detail_response,
            "get unknown execution report detail",
            code=4040,
            msg="执行记录不存在",
            data_type=(dict, list, type(None)),
        )
