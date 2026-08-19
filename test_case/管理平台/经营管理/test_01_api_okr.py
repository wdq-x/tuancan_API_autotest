# -*- coding: utf-8 -*-
"""OKR read models, validation, and a cleaned-up personal objective lifecycle."""
from datetime import date
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, default_headers
from utils.api_test_support import assert_auth_required, assert_success, assert_validation_error, management_client
from utils.http_client import HttpClient


BASE_URL = "/v1/okr"
CYCLE = "%s-Q3" % date.today().year


def _find_key(nodes, title):
    for node in nodes or []:
        if isinstance(node, dict):
            if node.get("title") == title and node.get("key"):
                return node["key"]
            found = _find_key(node.get("children"), title)
            if found:
                return found
    return None


@pytest.fixture(scope="module")
def okr_client():
    return management_client()


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-经营管理-OKR 管理")
class TestOKR管理:
    @allure.feature("访问控制")
    @allure.title("未登录访问我的 OKR 被拒绝")
    @allure.step("执行：未登录访问我的 OKR 被拒绝")
    def test_anonymous_my_okr_is_rejected(self):
        assert_auth_required(HttpClient(headers=default_headers.copy()).get(BASE_URL + "/my", params={"cycle": CYCLE}), "anonymous my OKR")

    @allure.feature("树形结构选择与概览")
    @allure.title("OKR 树成员绩效部门公司与概览查询")
    @allure.step("执行：OKR 树成员绩效部门公司与概览查询")
    def test_okr_read_models_return_success_envelopes(self, okr_client):
        requests = (
            ("/my", {"cycle": CYCLE}, "get my OKR"),
            ("/members", None, "get OKR members"),
            ("/performance", {"cycle": "%s-%02d" % (date.today().year, date.today().month)}, "get monthly OKR performance"),
            ("/departments", None, "get OKR departments"),
            ("/company", {"cycle": CYCLE}, "get company OKR"),
            ("/operation-logs", {"page": 1, "page_size": 10}, "get OKR operation logs"),
            ("/review", {"year": str(date.today().year)}, "get annual OKR review"),
            ("/overview", {"scope": "my", "cycle": CYCLE}, "get my OKR overview"),
        )
        for suffix, params, action in requests:
            payload = assert_success(okr_client.get(BASE_URL + suffix, params=params), action)
            assert payload.get("data") is not None, payload
        assert_validation_error(
            okr_client.post(BASE_URL + "/node", json={}),
            "create an empty OKR node",
            (("body", "scope"), ("body", "cycle"), ("body", "type")),
        )

    @allure.feature("个人目标生命周期")
    @allure.title("个人 OKR 目标创建编辑删除与数据清理")
    @allure.step("执行：个人 OKR 目标创建编辑删除与数据清理")
    def test_personal_objective_create_update_and_delete_are_cleaned_up(self, okr_client):
        if not ENABLE_WRITE_TESTS:
            pytest.skip("write tests are disabled through ENABLE_WRITE_TESTS")
        title = "AT-OKR-objective-%s" % uuid4().hex[:12]
        key = None
        try:
            created = assert_success(
                okr_client.post(BASE_URL + "/node", json={
                    "scope": "my",
                    "cycle": CYCLE,
                    "type": "Objective",
                    "title": title,
                    "weight": 1,
                }),
                "create temporary personal objective",
            )
            key = _find_key(created.get("data"), title)
            assert key, created
            updated = assert_success(
                okr_client.patch(BASE_URL + "/node/%s" % key, params={"scope": "my", "cycle": CYCLE}, json={"title": title + " updated", "progress": 25}),
                "update temporary personal objective",
            )
            assert _find_key(updated.get("data"), title + " updated"), updated
            assert_success(
                okr_client.delete(BASE_URL + "/node/%s" % key, params={"scope": "my", "cycle": CYCLE}),
                "delete temporary personal objective",
            )
            key = None
        finally:
            if key:
                try:
                    okr_client.delete(BASE_URL + "/node/%s" % key, params={"scope": "my", "cycle": CYCLE})
                except Exception:
                    pass
