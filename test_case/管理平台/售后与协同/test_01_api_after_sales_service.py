# -*- coding: utf-8 -*-
"""After-sales service workbench and ticket API regression tests."""
import allure
import pytest

from config.project_information import default_headers
from utils.api_test_support import assert_auth_required, assert_client_error, assert_success, assert_validation_error, first_id, management_client
from utils.http_client import HttpClient


BASE_URL = "/v1/after-sales-service"


@pytest.fixture(scope="module")
def after_sales_service_client():
    return management_client()


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-售后与协同-售后服务")
class Test售后服务:
    @allure.feature("访问控制")
    @allure.title("未登录访问售后工作台被拒绝")
    @allure.step("执行：未登录访问售后工作台被拒绝")
    def test_anonymous_workbench_access_is_rejected(self):
        assert_auth_required(HttpClient(headers=default_headers.copy()).get(BASE_URL + "/workbench"), "anonymous after-sales workbench")

    @allure.feature("工作台与看板")
    @allure.title("售后工作台工单列表与看板查询")
    @allure.step("执行：售后工作台工单列表与看板查询")
    def test_workbench_ticket_list_and_dashboard_return_data(self, after_sales_service_client):
        for path, params, action in (
            ("/workbench", None, "get after-sales workbench"),
            ("/tickets", {"page": 1, "page_size": 10}, "list after-sales tickets"),
            ("/dashboard", None, "get after-sales dashboard"),
        ):
            payload = assert_success(after_sales_service_client.get(BASE_URL + path, params=params), action)
            assert payload.get("data") is not None, payload

    @allure.feature("工单校验")
    @allure.title("未知工单操作被拒绝且不修改数据")
    @allure.step("执行：未知工单操作被拒绝且不修改数据")
    def test_unknown_ticket_actions_are_rejected_without_mutation(self, after_sales_service_client):
        missing_ticket_id = 2147483647
        assert_client_error(
            after_sales_service_client.get("%s/tickets/%s" % (BASE_URL, missing_ticket_id)),
            "get an unknown after-sales ticket",
            code=4040,
            msg="售后工单不存在",
            data_type=type(None),
        )
        assert_validation_error(
            after_sales_service_client.post("%s/tickets/%s/replies" % (BASE_URL, missing_ticket_id), json={}),
            "reply to an unknown after-sales ticket",
            (("body", "content"),),
        )
        assert_validation_error(
            after_sales_service_client.post("%s/tickets/%s/close" % (BASE_URL, missing_ticket_id), json={}),
            "close an unknown after-sales ticket",
            (("body", "content"),),
        )
        assert_client_error(
            after_sales_service_client.post("%s/tickets/%s/retry-sync" % (BASE_URL, missing_ticket_id), json={}),
            "retry sync for an unknown after-sales ticket",
            code=4040,
            msg="工单不存在",
            data_type=type(None),
        )
