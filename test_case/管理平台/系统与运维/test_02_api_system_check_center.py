# -*- coding: utf-8 -*-
"""Read-only regression coverage for the system check centre.

The three POST endpoints generate or backfill shared operational data. They are
deliberately excluded from unattended regression execution; their read models
are covered here without changing any production-like data.
"""
import allure

from utils.api_test_support import assert_success
from utils.http_client import HttpClient


BASE_URL = "/v1/system-check-center"


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与运维-系统巡检中心")
class Test系统巡检中心:
    @allure.feature("运营看板")
    @allure.title("系统巡检中心看板查询模型")
    @allure.step("执行：系统巡检中心看板查询模型")
    def test_dashboard_read_models_return_success_envelopes(self):
        client = HttpClient()
        requests = (
            ("/summary", {"days": 7}, "get system check summary"),
            ("/filter-options", None, "get system check filter options"),
            ("/top-customers", {"limit": 10}, "get top system check customers"),
            ("/access-records", {"page": 1, "page_size": 10}, "list access records"),
            ("/charts", {"days": 7}, "get system check charts"),
        )
        for suffix, params, action in requests:
            payload = assert_success(client.get(BASE_URL + suffix, params=params), action)
            assert payload.get("data") is not None, payload
