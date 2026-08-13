# -*- coding: utf-8 -*-
"""基础单位和项目爬虫接口自动化测试。

单位链路使用 API 创建的 AT 客户并通过业务删除接口回收。爬虫项目当前没有删除
接口，因此使用固定的 ``AT-AUTOMATION-CRAWLER-CONTRACT-V1`` project_id 验证幂等
提交；首次运行最多创建一条明确标识的测试记录，后续运行只会命中 skipped 分支。
"""
from datetime import date

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS
from utils.api_test_data import create_normal_customer, delete_customer
from utils.api_test_support import assert_success, management_client


UNITS_URL = "/v1/units"
CRAWLER_DATA_URL = "/v1/crawler-data"
CRAWLER_PROJECTS_URL = "/v1/projects"
CRAWLER_PROJECT_DETAIL_URL = "/v1/project_detail"
CRAWLER_PROJECT_ID = "AT-AUTOMATION-CRAWLER-CONTRACT-V1"


def _require_write_tests():
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _page_data(payload, action):
    data = payload.get("data")
    assert isinstance(data, dict) and isinstance(data.get("items"), list), "%s paging contract failed: %s" % (action, payload)
    assert isinstance(data.get("total"), int) and data["total"] >= 0, "%s total contract failed: %s" % (action, payload)
    return data


def _crawler_payload():
    today = date.today().isoformat()
    return {
        "project_id": CRAWLER_PROJECT_ID,
        "title": "AT 自动化项目爬虫契约",
        "publish_time": "%s 09:00:00" % today,
        "area": "自动化测试区",
        "province": "测试省",
        "city": "测试市",
        "project_type": "采购公告",
        "tender_status": "进行中",
        "project_amount": "0",
        "detail_url": "https://example.invalid/at-crawler-contract",
        "project_number": "AT-CRAWLER-CONTRACT-V1",
        "content": "AT crawler API regression record; intentionally idempotent because delete API is unavailable.",
    }


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-经营管理-基础单位与项目爬虫")
class Test基础单位:
    @allure.feature("客户单位关系")
    def test_客户单位_创建列表详情更新删除完整链路(self):
        _require_write_tests()
        client = management_client()
        customer_id = None
        unit_id = None
        try:
            customer = create_normal_customer(client, "AT-unit-customer")
            customer_id = customer["id"]
            unit_name = "AT-基础单位-%s" % customer["name"].rsplit("-", 1)[-1]
            with allure.step("通过客户单位兼容路径创建 AT 单位"):
                create_payload = assert_success(
                    client.post(
                        "/v1/customers/%s/units" % customer_id,
                        json={
                            "customer_id": customer_id,
                            "name": unit_name,
                            "unit_type": "school",
                            "contact_person": "AT 单位联系人",
                            "contact_phone": "13800000000",
                            "address": "AT 自动化测试地址",
                            "dining_count": 1,
                        },
                    ),
                    "create AT customer unit",
                )
            unit = create_payload.get("data") or {}
            unit_id = unit.get("id")
            assert isinstance(unit_id, int) and unit_id > 0, create_payload
            assert unit.get("customer_id") == customer_id and unit.get("name") == unit_name, create_payload

            with allure.step("从客户关系和通用单位列表回查 AT 单位"):
                customer_units_payload = assert_success(
                    client.get("/v1/customers/%s/units" % customer_id, params={"name": unit_name, "page": 1, "page_size": 10}),
                    "list AT customer units",
                )
                all_units_payload = assert_success(
                    client.get(UNITS_URL, params={"customer_id": customer_id, "name": unit_name, "page": 1, "page_size": 10}),
                    "list AT units via generic endpoint",
                )
            assert any(item.get("id") == unit_id for item in _page_data(customer_units_payload, "list AT customer units")["items"]), customer_units_payload
            assert any(item.get("id") == unit_id for item in _page_data(all_units_payload, "list AT units via generic endpoint")["items"]), all_units_payload

            with allure.step("读取并更新 AT 单位"):
                detail_payload = assert_success(client.get("%s/%s" % (UNITS_URL, unit_id)), "get AT unit")
                update_payload = assert_success(
                    client.put(
                        "%s/%s" % (UNITS_URL, unit_id),
                        json={"name": "%s 已编辑" % unit_name, "contact_person": "AT 已编辑联系人", "dining_count": 2},
                    ),
                    "update AT unit",
                )
            assert (detail_payload.get("data") or {}).get("id") == unit_id, detail_payload
            assert (update_payload.get("data") or {}).get("name") == "%s 已编辑" % unit_name, update_payload

            with allure.step("通过客户单位路径逻辑删除 AT 单位"):
                delete_payload = assert_success(
                    client.delete("/v1/customers/%s/units/%s" % (customer_id, unit_id)),
                    "delete AT customer unit",
                )
            assert delete_payload.get("data") is None, delete_payload
            unit_id = None
        finally:
            if unit_id:
                try:
                    client.delete("/v1/customers/%s/units/%s" % (customer_id, unit_id))
                except Exception:
                    pass
            delete_customer(client, customer_id)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-经营管理-基础单位与项目爬虫")
class Test项目爬虫:
    @allure.feature("爬虫项目")
    def test_爬虫提交_项目列表日期查询详情与幂等创建(self):
        _require_write_tests()
        client = management_client()
        project = _crawler_payload()

        # 先验证查询权限，再写入固定幂等 AT 记录，避免无权限环境产生无法继续验证的数据。
        with allure.step("确认测试账号可查询爬虫项目"):
            assert_success(
                client.get(CRAWLER_PROJECTS_URL, params={"title": project["title"], "page": 1, "page_size": 10}),
                "preflight crawler project list",
            )

        with allure.step("通过批量爬虫入口提交固定 AT 项目"):
            bulk_payload = assert_success(client.post(CRAWLER_DATA_URL, json=[project]), "submit idempotent AT crawler project")
        bulk_data = bulk_payload.get("data") or {}
        assert bulk_data.get("total_received") == 1, bulk_payload
        assert bulk_data.get("total_created", 0) + bulk_data.get("total_skipped", 0) == 1, bulk_payload

        with allure.step("按标题查询并获得持久化项目主键"):
            list_payload = assert_success(
                client.get(CRAWLER_PROJECTS_URL, params={"title": project["title"], "page": 1, "page_size": 10}),
                "list idempotent AT crawler project",
            )
        items = _page_data(list_payload, "list idempotent AT crawler project")["items"]
        stored = next((item for item in items if item.get("project_id") == CRAWLER_PROJECT_ID), None)
        assert stored is not None, list_payload
        stored_id = stored.get("id")
        assert isinstance(stored_id, int) and stored_id > 0, stored

        with allure.step("按发布日期和详情接口回查同一 AT 项目"):
            by_date_payload = assert_success(
                client.get("%s/date/%s" % (CRAWLER_PROJECTS_URL, date.today().isoformat())),
                "list AT crawler projects by publish date",
            )
            detail_response = client.get(CRAWLER_PROJECT_DETAIL_URL, params={"project_id": stored_id})
        by_date_items = by_date_payload.get("data") or []
        assert any(item.get("id") == stored_id for item in by_date_items), by_date_payload
        detail_payload = detail_response.json()
        assert detail_response.status_code == 200 and detail_payload.get("code") == 20000, detail_payload
        assert (detail_payload.get("data") or {}).get("id") == stored_id, detail_payload

        with allure.step("通过单条创建入口验证相同 project_id 幂等返回"):
            single_payload = assert_success(client.post(CRAWLER_PROJECTS_URL, json=project), "create existing AT crawler project")
        assert (single_payload.get("data") or {}).get("id") == stored_id, single_payload
