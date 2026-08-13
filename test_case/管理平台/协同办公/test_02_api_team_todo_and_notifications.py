# -*- coding: utf-8 -*-
"""Team tasks and WeChat notification API regression tests."""
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, default_headers
from utils.api_test_support import assert_auth_required, assert_success, assert_validation_error, assert_client_error, first_id, management_client
from utils.http_client import HttpClient


TODO_URL = "/v1/team-todo"
NOTIFICATION_URL = "/v1/todo-notifications"


@pytest.fixture(scope="module")
def collaboration_client():
    return management_client()


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-协同办公-团队待办")
class Test团队待办:
    @allure.feature("访问控制")
    @allure.title("未登录访问团队待办列表被拒绝")
    def test_anonymous_team_todo_list_is_rejected(self):
        assert_auth_required(HttpClient(headers=default_headers.copy()).get(TODO_URL), "anonymous team todo list")

    @allure.feature("列表与人员选择")
    @allure.title("团队待办列表与处理人选择查询")
    def test_team_todo_list_and_assignee_selector_are_available(self, collaboration_client):
        todos = assert_success(collaboration_client.get(TODO_URL, params={"page": 1, "page_size": 10}), "list team todos")
        assert isinstance((todos.get("data") or {}).get("items"), list), todos
        users = assert_success(collaboration_client.get(TODO_URL + "/users", params={"page": 1, "page_size": 100}), "list team todo assignees")
        assert isinstance((users.get("data") or {}).get("items"), list), users
        assert_validation_error(
            collaboration_client.post(TODO_URL, json={}),
            "create empty team todo",
            (("body", "work_item"), ("body", "assignee_id")),
        )
        assert_client_error(
            collaboration_client.get(TODO_URL + "/2147483647"),
            "get unknown team todo",
            code=4040,
            msg="待办不存在",
            data_type=type(None),
        )

    @allure.feature("待办生命周期")
    @allure.title("团队待办创建更新删除与数据清理")
    def test_team_todo_create_update_and_delete_are_cleaned_up(self, collaboration_client):
        if not ENABLE_WRITE_TESTS:
            pytest.skip("write tests are disabled through ENABLE_WRITE_TESTS")
        users = assert_success(collaboration_client.get(TODO_URL + "/users", params={"page": 1, "page_size": 100}), "get todo assignee candidates")
        assignee_id = first_id(users)
        if not assignee_id:
            pytest.skip("no active user is available as a temporary team todo assignee")

        todo_id = None
        try:
            payload = assert_success(
                collaboration_client.post(TODO_URL, json={
                    "work_category": "API regression",
                    "work_item": "AT-team-todo-%s" % uuid4().hex[:12],
                    "assignee_id": assignee_id,
                    "priority": "中",
                    "status": "待开始",
                }),
                "create temporary team todo",
            )
            todo_id = (payload.get("data") or {}).get("id")
            assert isinstance(todo_id, int) and todo_id > 0, payload
            updated = assert_success(
                collaboration_client.patch(TODO_URL + "/%s" % todo_id, json={"completion_rate": 100}),
                "complete temporary team todo",
            )
            assert (updated.get("data") or {}).get("completion_rate") == 100, updated
            assert_success(collaboration_client.delete(TODO_URL + "/%s" % todo_id), "delete temporary team todo")
            todo_id = None
        finally:
            if todo_id:
                try:
                    collaboration_client.delete(TODO_URL + "/%s" % todo_id)
                except Exception:
                    pass


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-协同办公-待办通知")
class Test待办通知:
    @allure.feature("访问控制")
    @allure.title("未登录访问待办通知配置被拒绝")
    def test_anonymous_notification_configuration_is_rejected(self):
        assert_auth_required(
            HttpClient(headers=default_headers.copy()).get(NOTIFICATION_URL + "/configurations"),
            "anonymous notification configurations",
        )

    @allure.feature("配置与授权入口")
    @allure.title("通知配置查询保存校验与微信授权入口")
    def test_notification_read_models_and_invalid_save_contract(self, collaboration_client):
        payload = assert_success(collaboration_client.get(NOTIFICATION_URL + "/configurations"), "get notification configurations")
        assert isinstance((payload.get("data") or {}).get("configurations"), list), payload
        bindings = assert_success(collaboration_client.get(NOTIFICATION_URL + "/wechat/bindings"), "list WeChat bindings")
        assert bindings.get("data") is not None, bindings
        assert_client_error(
            collaboration_client.put(NOTIFICATION_URL + "/configurations", json={"configurations": []}),
            "save an empty notification configuration",
            code=4100,
            msg="请至少保存一项通知配置",
            data_type=type(None),
        )

        entry_page = collaboration_client.get(NOTIFICATION_URL + "/wechat/authorize")
        assert entry_page.status_code == 200, entry_page.text[:500]
        assert "text/html" in entry_page.headers.get("Content-Type", ""), entry_page.headers
