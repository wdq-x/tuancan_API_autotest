# -*- coding: utf-8 -*-
"""移动端客户管理接口自动化测试。

接口契约来自 ``canteen_operate_platfrom_app`` 的客户管理模块：

- ``customer_request.dart``：客户列表、详情、新增、删除、续费与状态更新。
- ``customer_model.dart``：列表筛选参数和客户提交字段。
- ``add_customer_controller.dart``：移动端新增客户必须先选择来源线索；普通新增
  调用 ``POST /v1/customers``，线索转换调用 ``POST /v1/leads/{id}/convert-to-customer``。

写入场景只创建 ``AT-移动端客户-``、``AT-移动端客户线索-`` 前缀的临时数据，并在
用例结束时删除。来源渠道复用环境已有的合作中渠道，避免修改环境原有配置。
"""
from datetime import date, timedelta
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, MOBILE_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
CUSTOMERS_URL = "/v1/customers"
LEADS_URL = "/v1/leads"
CHANNEL_OPTIONS_URL = "/v1/channels/options"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
PARAM_ERROR_CODE = 4100
UNAUTHORIZED_CODE = 4010
FORBIDDEN_CODE = 4030
CUSTOMER_NOT_FOUND_CODE = 5300
NAME_ALREADY_EXISTS_CODE = 5001

MOBILE_DEPLOYMENT_TYPES = {"small_saas", "big_saas", "private", "lan", "offline"}
MOBILE_CUSTOMER_TYPES = {"enterprise", "government", "education", "medical", "other"}
CUSTOMER_STATUSES = {"normal", "disabled", "expired"}
CUSTOMER_REQUIRED_FIELDS = {
    "id",
    "name",
    "deployment_type",
    "customer_type",
    "manager_name",
    "manager_phone",
    "pos_count",
    "dining_limit",
    "service_period",
    "valid_start",
    "valid_end",
    "status",
    "attachments",
    "is_deleted",
    "call_domain_api",
}


def _require_write_tests():
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已通过 ENABLE_WRITE_TESTS 关闭")


def _parse_json(response, action):
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            "%s 返回非 JSON。url=%s, status=%s, body=%s"
            % (action, response.url, response.status_code, response.text[:500])
        ) from exc
    assert isinstance(payload, dict), "%s 响应根节点应为对象：%r" % (action, payload)
    return payload


def _assert_success(response, action):
    assert response.status_code == 200, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = _parse_json(response, action)
    if payload.get("code") == FORBIDDEN_CODE:
        pytest.skip("测试账号缺少移动端客户或线索管理权限")
    assert payload.get("code") == SUCCESS_CODE, "%s 业务失败：%s" % (action, payload)
    assert "data" in payload, "%s 成功响应缺少 data：%s" % (action, payload)
    return payload


def _assert_error_code(response, action, expected_code, expected_http_status=200):
    assert response.status_code == expected_http_status, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = _parse_json(response, action)
    assert payload.get("code") == expected_code, "%s 错误码不正确：%s" % (action, payload)
    return payload


def _assert_page_payload(payload, action, expected_page, expected_page_size):
    data = payload["data"]
    assert isinstance(data, dict), "%s data 应为分页对象：%s" % (action, data)
    assert isinstance(data.get("items"), list), "%s data.items 应为数组：%s" % (action, data)
    assert isinstance(data.get("total"), int), "%s data.total 应为整数：%s" % (action, data)
    assert data.get("page") == expected_page, "%s 页码回显不正确：%s" % (action, data)
    assert data.get("page_size") == expected_page_size, "%s 每页数量回显不正确：%s" % (action, data)
    assert len(data["items"]) <= expected_page_size, "%s 返回条数超过 page_size：%s" % (action, data)
    return data


def _assert_customer_shape(customer, action, expected_customer_id=None):
    assert isinstance(customer, dict), "%s 客户项应为对象：%r" % (action, customer)
    missing_fields = CUSTOMER_REQUIRED_FIELDS - set(customer)
    assert not missing_fields, "%s 客户项缺少字段 %s：%s" % (action, missing_fields, customer)
    assert isinstance(customer["id"], int) and customer["id"] > 0, "%s 客户 id 非法：%s" % (action, customer)
    assert isinstance(customer["name"], str) and customer["name"].strip(), "%s 客户名称为空：%s" % (action, customer)
    assert customer["deployment_type"] in MOBILE_DEPLOYMENT_TYPES, "%s 部署模式非法：%s" % (action, customer)
    assert customer["customer_type"] in MOBILE_CUSTOMER_TYPES, "%s 客户类型非法：%s" % (action, customer)
    assert customer["status"] in CUSTOMER_STATUSES, "%s 客户状态非法：%s" % (action, customer)
    assert isinstance(customer["manager_name"], str) and customer["manager_name"], "%s 联系人为空：%s" % (action, customer)
    assert isinstance(customer["manager_phone"], str) and len(customer["manager_phone"]) == 11, "%s 联系电话异常：%s" % (action, customer)
    assert isinstance(customer["service_period"], int) and customer["service_period"] > 0, "%s 服务期限异常：%s" % (action, customer)
    assert isinstance(customer["attachments"], list), "%s 附件字段应为数组：%s" % (action, customer)
    assert isinstance(customer["is_deleted"], bool), "%s is_deleted 应为布尔值：%s" % (action, customer)
    assert isinstance(customer["call_domain_api"], bool), "%s call_domain_api 应为布尔值：%s" % (action, customer)
    if expected_customer_id is not None:
        assert customer["id"] == expected_customer_id, "%s 客户 id 不正确：%s" % (action, customer)


def _login_mobile_client(username, password):
    client = HttpClient(headers=default_headers.copy())
    response = client.post(
        LOGIN_URL,
        json={"username": username, "password": password, "client_type": "mobile"},
    )
    payload = _assert_success(response, "移动端客户管理账号登录")
    token = (payload.get("data") or {}).get("access_token")
    assert token, "移动端登录成功但未返回 access_token：%s" % payload
    client.headers["Authorization"] = "Bearer %s" % token
    return client


@pytest.fixture(scope="module")
def mobile_customer_client():
    """移动端和管理平台统一读取 MANAGEMENT_TEST_ACCOUNT 的配置结果。"""
    account = MOBILE_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录移动端客户管理")

    with allure.step("使用 client_type=mobile 登录并获取 Token"):
        client = _login_mobile_client(username, password)
    yield client
    client.headers.pop("Authorization", None)


def _mobile_customer_body(name=None, lead_id=None, **overrides):
    """按 CustomerCreateParams.toJson 构造移动端表单提交体。"""
    valid_start = date.today()
    body = {
        "name": name or "AT-移动端客户-%s" % uuid4().hex[:12],
        "deployment_type": "small_saas",
        "customer_type": "enterprise",
        "manager_name": "移动端自动化客户联系人",
        "manager_phone": "13900000000",
        "service_period": 1,
        "valid_start": valid_start.isoformat(),
        "valid_end": (valid_start + timedelta(days=365)).isoformat(),
        "dining_limit": 2,
        "pos_count": 1,
        "domain_name": "at-mobile-%s.example.invalid" % uuid4().hex[:10],
        "remarks": "移动端客户管理接口自动化临时数据，可安全删除",
        "call_domain_api": False,
        "attachments": [],
    }
    if lead_id is not None:
        body["lead_id"] = lead_id
    body.update(overrides)
    return body


def _get_active_channel(client):
    payload = _assert_success(
        client.get(CHANNEL_OPTIONS_URL, params={"status": "active", "limit": 500}),
        "获取移动端客户来源渠道选项",
    )
    channels = payload["data"]
    assert isinstance(channels, list), "移动端客户来源渠道选项 data 应为数组：%s" % payload
    for channel in channels:
        if isinstance(channel, dict) and isinstance(channel.get("id"), int) and channel["id"] > 0:
            return channel
    pytest.skip("当前测试环境没有可用于移动端客户来源线索的合作中渠道")


def _create_temporary_lead(client, channel):
    name = "AT-移动端客户线索-%s" % uuid4().hex[:12]
    payload = _assert_success(
        client.post(
            LEADS_URL,
            json={
                "name": name,
                "business_type": "enterprise",
                "status": "pending",
                "channel_id": channel["id"],
                "remark": "移动端客户管理自动化来源线索，可安全删除",
            },
        ),
        "创建移动端客户来源线索",
    )
    lead = payload["data"]
    assert isinstance(lead.get("id"), int) and lead["id"] > 0, "来源线索 id 非法：%s" % lead
    assert lead.get("name") == name, "来源线索名称不正确：%s" % lead
    assert lead.get("channel_id") == channel["id"], "来源线索渠道不正确：%s" % lead
    return lead


def _create_customer_from_selected_lead(client, lead, **overrides):
    """模拟新增客户页选择来源线索后调用 POST /customers 的流程。"""
    body = _mobile_customer_body(lead_id=lead["id"], **overrides)
    payload = _assert_success(client.post(CUSTOMERS_URL, json=body), "移动端新增客户")
    customer = payload["data"]
    _assert_customer_shape(customer, "移动端新增客户")
    assert customer["name"] == body["name"], "移动端新增客户名称不正确：%s" % customer
    assert customer.get("lead_id") == lead["id"], "移动端新增客户未关联所选线索：%s" % customer
    return customer, body


def _cleanup_temporary_customer(client, customer_id):
    if not customer_id:
        return
    try:
        client.delete("%s/%s" % (CUSTOMERS_URL, customer_id))
    except Exception:
        pass


def _cleanup_temporary_lead(client, lead_id):
    if not lead_id:
        return
    try:
        client.delete("%s/%s" % (LEADS_URL, lead_id), params={"delete_related_customer": "true"})
    except Exception:
        pass


@allure.parent_suite("接口自动化")
@allure.suite("移动端-客户管理")
class Test移动端客户管理查询:
    """覆盖移动端客户列表、详情入口和参数校验。"""

    @allure.feature("移动端鉴权")
    def test_未登录访问移动端客户列表_返回未授权(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Token 请求移动端客户列表"):
            response = anonymous_client.get(CUSTOMERS_URL, params={"page": 1, "page_size": 10})
        _assert_error_code(
            response,
            "未登录获取移动端客户列表",
            UNAUTHORIZED_CODE,
            expected_http_status=401,
        )

    @allure.feature("列表与筛选")
    def test_移动端客户列表_分页加载与基础筛选参数(self, mobile_customer_client):
        with allure.step("获取移动端客户列表首页"):
            first_page = _assert_success(
                mobile_customer_client.get(CUSTOMERS_URL, params={"page": 1, "page_size": 10}),
                "移动端客户列表首页",
            )
        first_data = _assert_page_payload(first_page, "移动端客户列表首页", expected_page=1, expected_page_size=10)
        for item in first_data["items"]:
            _assert_customer_shape(item, "移动端客户列表项")

        with allure.step("模拟滚动到底部加载移动端客户列表第二页"):
            second_page = _assert_success(
                mobile_customer_client.get(CUSTOMERS_URL, params={"page": 2, "page_size": 10}),
                "移动端客户列表第二页",
            )
        _assert_page_payload(second_page, "移动端客户列表第二页", expected_page=2, expected_page_size=10)

        with allure.step("按移动端部署模式和状态筛选客户"):
            filtered_page = _assert_success(
                mobile_customer_client.get(
                    CUSTOMERS_URL,
                    params={"deployment_type": "small_saas", "status": "normal", "page": 1, "page_size": 10},
                ),
                "移动端客户部署模式和状态筛选",
            )
        filtered_data = _assert_page_payload(filtered_page, "移动端客户部署模式和状态筛选", 1, 10)
        for item in filtered_data["items"]:
            assert item["deployment_type"] == "small_saas", item
            assert item["status"] == "normal", item

    @allure.feature("参数校验")
    def test_移动端客户_列表创建和详情参数校验(self, mobile_customer_client):
        with allure.step("移动端请求非法客户列表页码"):
            invalid_page_response = mobile_customer_client.get(CUSTOMERS_URL, params={"page": 0, "page_size": 10})
        _assert_error_code(invalid_page_response, "移动端客户列表非法页码", INVALID_PARAMS_CODE)

        invalid_bodies = [
            ("缺少全部必填字段", {}),
            (
                "联系电话格式非法",
                {
                    "name": "AT-移动端非法联系电话客户",
                    "deployment_type": "small_saas",
                    "customer_type": "enterprise",
                    "manager_name": "移动端自动化",
                    "manager_phone": "123",
                    "service_period": 1,
                },
            ),
        ]
        for action, body in invalid_bodies:
            with allure.step("移动端新增客户校验：%s" % action):
                response = mobile_customer_client.post(CUSTOMERS_URL, json=body)
            _assert_error_code(response, "移动端新增客户%s" % action, INVALID_PARAMS_CODE)

        with allure.step("移动端请求不存在的客户详情"):
            missing_detail_response = mobile_customer_client.get("%s/%s" % (CUSTOMERS_URL, 2147483647))
        _assert_error_code(missing_detail_response, "移动端不存在的客户详情", CUSTOMER_NOT_FOUND_CODE)

        with allure.step("移动端删除不存在的客户"):
            missing_delete_response = mobile_customer_client.delete("%s/%s" % (CUSTOMERS_URL, 2147483647))
        _assert_error_code(missing_delete_response, "移动端删除不存在的客户", CUSTOMER_NOT_FOUND_CODE)


@allure.parent_suite("接口自动化")
@allure.suite("移动端-客户管理")
class Test移动端客户管理业务链路:
    """覆盖新增、来源关联、详情、续费、状态变更、删除和线索转客户。"""

    @allure.feature("新增与详情")
    def test_移动端客户_选择线索创建查询删除完整链路(self, mobile_customer_client):
        """将新增、详情、列表回查和删除拆为独立闭环，便于 CI 定位失败环节。"""
        _require_write_tests()
        lead_id = None
        customer_id = None
        try:
            channel = _get_active_channel(mobile_customer_client)
            lead = _create_temporary_lead(mobile_customer_client, channel)
            lead_id = lead["id"]

            with allure.step("新增页选择来源线索并创建客户"):
                customer, body = _create_customer_from_selected_lead(mobile_customer_client, lead)
            customer_id = customer["id"]

            with allure.step("按客户名称从移动端列表回查新增记录"):
                list_payload = _assert_success(
                    mobile_customer_client.get(
                        CUSTOMERS_URL,
                        params={"name": body["name"], "page": 1, "page_size": 10},
                    ),
                    "移动端回查新增客户",
                )
            list_data = _assert_page_payload(list_payload, "移动端回查新增客户", 1, 10)
            assert any(item.get("id") == customer_id for item in list_data["items"]), list_data

            with allure.step("打开移动端客户详情"):
                detail_payload = _assert_success(
                    mobile_customer_client.get("%s/%s" % (CUSTOMERS_URL, customer_id)),
                    "移动端查询新增客户详情",
                )
            _assert_customer_shape(detail_payload["data"], "移动端查询新增客户详情", expected_customer_id=customer_id)

            with allure.step("从移动端客户详情删除新增客户"):
                delete_payload = _assert_success(
                    mobile_customer_client.delete("%s/%s" % (CUSTOMERS_URL, customer_id)),
                    "移动端删除新增客户",
                )
            assert delete_payload["data"].get("id") == customer_id, delete_payload
            deleted_customer_id = customer_id
            customer_id = None

            with allure.step("删除后详情接口返回客户不存在"):
                missing_response = mobile_customer_client.get("%s/%s" % (CUSTOMERS_URL, deleted_customer_id))
            _assert_error_code(missing_response, "移动端删除后查询客户", CUSTOMER_NOT_FOUND_CODE)
        finally:
            _cleanup_temporary_customer(mobile_customer_client, customer_id)
            _cleanup_temporary_lead(mobile_customer_client, lead_id)

    @allure.feature("新增异常")
    def test_移动端客户_同名客户创建被拒绝(self, mobile_customer_client):
        """移动端表单提交重复客户名称时，服务端应明确拒绝，不产生第二条客户。"""
        _require_write_tests()
        first_lead_id = None
        second_lead_id = None
        customer_id = None
        try:
            channel = _get_active_channel(mobile_customer_client)
            first_lead = _create_temporary_lead(mobile_customer_client, channel)
            second_lead = _create_temporary_lead(mobile_customer_client, channel)
            first_lead_id = first_lead["id"]
            second_lead_id = second_lead["id"]
            duplicate_name = "AT-移动端客户重名-%s" % uuid4().hex[:10]

            with allure.step("首次提交唯一客户名称"):
                customer, _ = _create_customer_from_selected_lead(
                    mobile_customer_client,
                    first_lead,
                    name=duplicate_name,
                )
            customer_id = customer["id"]

            with allure.step("使用另一来源线索重复提交相同客户名称"):
                duplicate_response = mobile_customer_client.post(
                    CUSTOMERS_URL,
                    json=_mobile_customer_body(name=duplicate_name, lead_id=second_lead_id),
                )
            _assert_error_code(duplicate_response, "移动端创建同名客户", NAME_ALREADY_EXISTS_CODE)
        finally:
            _cleanup_temporary_customer(mobile_customer_client, customer_id)
            _cleanup_temporary_lead(mobile_customer_client, first_lead_id)
            _cleanup_temporary_lead(mobile_customer_client, second_lead_id)

    @allure.feature("新增与详情")
    def test_移动端客户_从选择线索新增筛选详情与附件(self, mobile_customer_client):
        _require_write_tests()
        lead_id = None
        customer_id = None
        try:
            channel = _get_active_channel(mobile_customer_client)
            lead = _create_temporary_lead(mobile_customer_client, channel)
            lead_id = lead["id"]
            attachment = {
                "file_name": "AT-移动端客户资料.txt",
                "original_name": "AT-移动端客户资料.txt",
                "file_url": "https://example.com/at-mobile-customer.txt",
                "file_size": 12,
                "mime_type": "text/plain",
                "extension": "txt",
            }

            with allure.step("新增页选择来源线索后提交客户表单"):
                customer, body = _create_customer_from_selected_lead(
                    mobile_customer_client,
                    lead,
                    attachments=[attachment],
                )
            customer_id = customer["id"]
            assert customer.get("channel_id") == channel["id"], "客户未继承来源线索渠道：%s" % customer
            assert customer.get("channel_name") == channel.get("name"), "客户来源渠道名称不正确：%s" % customer

            with allure.step("按移动端名称、部署、渠道、线索、域名、状态和日期筛选新增客户"):
                list_payload = _assert_success(
                    mobile_customer_client.get(
                        CUSTOMERS_URL,
                        params={
                            "name": body["name"],
                            "deployment_type": body["deployment_type"],
                            "channel_name": channel.get("name"),
                            "lead_id": lead_id,
                            "domain_name": body["domain_name"],
                            "status": "normal",
                            # 后端将 end_time 按当天 00:00:00 处理，范围末端取次日以覆盖当天创建记录。
                            "start_time": (date.today() - timedelta(days=1)).isoformat(),
                            "end_time": (date.today() + timedelta(days=1)).isoformat(),
                            "valid_start_time": body["valid_start"],
                            "valid_end_time": body["valid_end"],
                            "page": 1,
                            "page_size": 10,
                        },
                    ),
                    "移动端客户组合筛选",
                )
            list_data = _assert_page_payload(list_payload, "移动端客户组合筛选", 1, 10)
            assert any(item.get("id") == customer_id for item in list_data["items"]), list_data

            with allure.step("打开移动端客户详情，验证来源关系和附件展示数据"):
                detail_payload = _assert_success(
                    mobile_customer_client.get("%s/%s" % (CUSTOMERS_URL, customer_id)),
                    "移动端客户详情",
                )
            detail = detail_payload["data"]
            _assert_customer_shape(detail, "移动端客户详情", expected_customer_id=customer_id)
            assert detail.get("lead_id") == lead_id, detail
            assert detail.get("channel_id") == channel["id"], detail
            assert len(detail["attachments"]) == 1, detail
            customer_id = None
        finally:
            _cleanup_temporary_customer(mobile_customer_client, customer_id)
            _cleanup_temporary_lead(mobile_customer_client, lead_id)

    @allure.feature("续费与状态")
    def test_移动端客户_续费禁用启用和删除(self, mobile_customer_client):
        _require_write_tests()
        lead_id = None
        customer_id = None
        try:
            channel = _get_active_channel(mobile_customer_client)
            lead = _create_temporary_lead(mobile_customer_client, channel)
            lead_id = lead["id"]
            customer, body = _create_customer_from_selected_lead(mobile_customer_client, lead)
            customer_id = customer["id"]
            renew_start = date.today()
            renew_end = renew_start + timedelta(days=365)

            with allure.step("从详情页续费弹窗提交新增一年服务期限"):
                renew_payload = _assert_success(
                    mobile_customer_client.put(
                        "%s/%s/renew" % (CUSTOMERS_URL, customer_id),
                        json={
                            "service_period": 1,
                            "valid_start": renew_start.isoformat(),
                            "valid_end": renew_end.isoformat(),
                        },
                    ),
                    "移动端客户续费",
                )
            renewed = renew_payload["data"]
            assert renewed.get("service_period") == body["service_period"] + 1, renewed
            assert str(renewed.get("valid_start")) == renew_start.isoformat(), renewed
            assert str(renewed.get("valid_end")) == renew_end.isoformat(), renewed

            with allure.step("移动端提交非法客户状态应被接口拒绝"):
                invalid_status_response = mobile_customer_client.put(
                    "%s/%s/status" % (CUSTOMERS_URL, customer_id),
                    json={"status": "not-supported"},
                )
            _assert_error_code(invalid_status_response, "移动端更新非法客户状态", PARAM_ERROR_CODE)

            with allure.step("从客户操作菜单禁用并重新启用客户"):
                disabled_payload = _assert_success(
                    mobile_customer_client.put(
                        "%s/%s/status" % (CUSTOMERS_URL, customer_id),
                        json={"status": "disabled"},
                    ),
                    "移动端禁用客户",
                )
                enabled_payload = _assert_success(
                    mobile_customer_client.put(
                        "%s/%s/status" % (CUSTOMERS_URL, customer_id),
                        json={"status": "normal"},
                    ),
                    "移动端启用客户",
                )
            assert disabled_payload["data"].get("status") == "disabled", disabled_payload
            assert enabled_payload["data"].get("status") == "normal", enabled_payload

            with allure.step("从移动端客户详情删除临时客户"):
                delete_payload = _assert_success(
                    mobile_customer_client.delete("%s/%s" % (CUSTOMERS_URL, customer_id)),
                    "移动端删除客户",
                )
            assert delete_payload["data"].get("id") == customer_id, delete_payload
            deleted_customer_id = customer_id
            customer_id = None

            with allure.step("删除后移动端客户详情不可见"):
                deleted_detail_response = mobile_customer_client.get("%s/%s" % (CUSTOMERS_URL, deleted_customer_id))
            _assert_error_code(deleted_detail_response, "移动端查询已删除客户详情", CUSTOMER_NOT_FOUND_CODE)
        finally:
            _cleanup_temporary_customer(mobile_customer_client, customer_id)
            _cleanup_temporary_lead(mobile_customer_client, lead_id)

    @allure.feature("线索转客户")
    def test_移动端客户_线索转客户表单和关联清理(self, mobile_customer_client):
        _require_write_tests()
        lead_id = None
        try:
            channel = _get_active_channel(mobile_customer_client)
            lead = _create_temporary_lead(mobile_customer_client, channel)
            lead_id = lead["id"]
            body = _mobile_customer_body(lead_id=lead_id)

            with allure.step("从线索转客户入口提交移动端客户表单"):
                convert_payload = _assert_success(
                    mobile_customer_client.post("%s/%s/convert-to-customer" % (LEADS_URL, lead_id), json=body),
                    "移动端线索转客户",
                )
            data = convert_payload["data"] or {}
            converted_lead = data.get("lead") or {}
            customer = data.get("customer") or {}
            customer_id = customer.get("id")
            _assert_customer_shape(customer, "移动端线索转客户返回客户")
            assert converted_lead.get("id") == lead_id, convert_payload
            assert converted_lead.get("status") == "converted", convert_payload
            assert customer.get("lead_id") == lead_id, convert_payload
            assert customer.get("channel_id") == channel["id"], convert_payload

            with allure.step("删除已转化来源线索时联动清理客户"):
                delete_payload = _assert_success(
                    mobile_customer_client.delete(
                        "%s/%s" % (LEADS_URL, lead_id),
                        params={"delete_related_customer": "true"},
                    ),
                    "移动端删除已转化来源线索",
                )
            deleted_customer_ids = delete_payload["data"].get("deleted_related_customer_ids") or []
            assert customer_id in deleted_customer_ids, "删除线索未联动清理客户：%s" % delete_payload
            lead_id = None
        finally:
            _cleanup_temporary_lead(mobile_customer_client, lead_id)
