# -*- coding: utf-8 -*-
"""基础单位接口自动化测试。"""

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS
from utils.api_test_data import create_normal_customer, delete_customer
from utils.api_test_support import assert_success, management_client


UNITS_URL = "/v1/units"


def _require_write_tests():
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _page_data(payload, action):
    data = payload.get("data")
    assert isinstance(data, dict) and isinstance(data.get("items"), list), "%s paging contract failed: %s" % (action, payload)
    assert isinstance(data.get("total"), int) and data["total"] >= 0, "%s total contract failed: %s" % (action, payload)
    return data


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-经营管理-基础单位")
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
