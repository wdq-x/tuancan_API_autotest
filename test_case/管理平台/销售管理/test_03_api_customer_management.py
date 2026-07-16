# -*- coding: utf-8 -*-
"""管理平台销售管理-客户管理接口自动化测试。

测试环境、管理平台账号和写操作开关只从
``config/project_information.py`` 读取。所有新增数据均使用 ``AT-`` 前缀；
客户删除接口为软删除，写入链路结束时会调用该接口将临时客户从正常列表移除。

``POST /customers/check-expiration`` 会扫描并更新全环境客户状态，属于运维任务，
不在常规接口回归中自动调用，避免影响非测试客户。
"""
from datetime import date, timedelta
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, MANAGEMENT_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
CHANNELS_URL = "/v1/channels"
CHANNEL_META_URL = "/v1/channels/meta"
LEADS_URL = "/v1/leads"
CUSTOMERS_URL = "/v1/customers"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
PARAM_ERROR_CODE = 4100
UNAUTHORIZED_CODE = 4010
FORBIDDEN_CODE = 4030
NAME_ALREADY_EXISTS_CODE = 5001
CUSTOMER_NOT_FOUND_CODE = 5300

DEPLOYMENT_TYPES = {
    "public_cloud",
    "private_cloud",
    "iot_edge",
    "k8s",
    "offline",
    "big_saas",
    "small_saas",
    "private",
    "lan",
}
CUSTOMER_TYPES = {"education", "enterprise", "government", "medical", "finance", "military", "other", "school"}
CUSTOMER_STATUSES = {"normal", "disabled", "expired"}
CUSTOMER_REQUIRED_FIELDS = {
    "id",
    "name",
    "deployment_type",
    "customer_type",
    "manager_name",
    "manager_phone",
    "service_period",
    "status",
    "attachments",
    "is_deleted",
}


def _require_write_tests():
    """关闭全局写操作开关时，明确跳过会创建客户的业务链路。"""
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _parse_json(response, action):
    """解析 JSON 响应，并在失败信息中保留必要的定位上下文。"""
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            "%s 返回非 JSON。url=%s, status=%s, body=%s"
            % (action, response.url, response.status_code, response.text[:500])
        ) from exc
    assert isinstance(payload, dict), "%s 响应根节点应为对象，实际为 %r" % (action, payload)
    return payload


def _assert_success(response, action):
    """校验管理平台成功响应，并把账号权限不符标记为跳过。"""
    assert response.status_code == 200, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = _parse_json(response, action)
    if payload.get("code") == FORBIDDEN_CODE:
        pytest.skip("登录账号缺少客户、线索或临时来源渠道所需权限")
    assert payload.get("code") == SUCCESS_CODE, "%s 业务失败：%s" % (action, payload)
    assert "data" in payload, "%s 成功响应缺少 data：%s" % (action, payload)
    return payload


def _assert_error_code(response, action, expected_code, expected_http_status=200):
    """校验统一错误响应的 HTTP 状态与业务码。"""
    assert response.status_code == expected_http_status, "%s HTTP 状态异常：%s" % (action, response.text)
    payload = _parse_json(response, action)
    assert payload.get("code") == expected_code, "%s 错误码不正确：%s" % (action, payload)
    return payload


def _assert_page_payload(payload, action, expected_page=None, expected_page_size=None):
    """校验客户列表、已删除列表和操作日志的分页结构。"""
    data = payload["data"]
    assert isinstance(data, dict), "%s data 应为分页对象，实际为 %r" % (action, data)
    assert isinstance(data.get("items"), list), "%s data.items 应为数组：%s" % (action, data)
    assert isinstance(data.get("total"), int), "%s data.total 应为整数：%s" % (action, data)
    assert isinstance(data.get("page"), int), "%s data.page 应为整数：%s" % (action, data)
    assert isinstance(data.get("page_size"), int), "%s data.page_size 应为整数：%s" % (action, data)
    if expected_page is not None:
        assert data["page"] == expected_page, "%s 页码回显不正确：%s" % (action, data)
    if expected_page_size is not None:
        assert data["page_size"] == expected_page_size, "%s 每页数量回显不正确：%s" % (action, data)
    assert len(data["items"]) <= data["page_size"], "%s 返回条数超过 page_size：%s" % (action, data)
    return data


def _assert_customer_shape(customer, action, expected_customer_id=None):
    """校验客户创建、详情和更新接口返回的核心数据结构。"""
    assert isinstance(customer, dict), "%s 客户项应为对象，实际为 %r" % (action, customer)
    missing_fields = CUSTOMER_REQUIRED_FIELDS - set(customer)
    assert not missing_fields, "%s 客户项缺少字段：%s；实际=%s" % (action, missing_fields, customer)
    assert isinstance(customer["id"], int) and customer["id"] > 0, "%s 客户 id 非法：%s" % (action, customer)
    assert isinstance(customer["name"], str) and customer["name"].strip(), "%s 客户名称为空：%s" % (action, customer)
    assert customer["deployment_type"] in DEPLOYMENT_TYPES, "%s 部署模式不合法：%s" % (action, customer)
    assert customer["customer_type"] in CUSTOMER_TYPES, "%s 客户类型不合法：%s" % (action, customer)
    assert customer["status"] in CUSTOMER_STATUSES, "%s 客户状态不合法：%s" % (action, customer)
    assert isinstance(customer["manager_name"], str) and customer["manager_name"], "%s 客户联系人为空：%s" % (action, customer)
    assert isinstance(customer["manager_phone"], str) and len(customer["manager_phone"]) == 11, "%s 客户联系电话异常：%s" % (action, customer)
    assert isinstance(customer["service_period"], int) and customer["service_period"] > 0, "%s 服务期限异常：%s" % (action, customer)
    assert isinstance(customer["attachments"], list), "%s 附件字段应为数组：%s" % (action, customer)
    assert isinstance(customer["is_deleted"], bool), "%s is_deleted 应为布尔值：%s" % (action, customer)
    if expected_customer_id is not None:
        assert customer["id"] == expected_customer_id, "%s 客户 id 不正确：%s" % (action, customer)


def _login_client(username, password, action):
    """登录内部账号，返回配置了 Bearer Token 的客户端。"""
    client = HttpClient(headers=default_headers.copy())
    response = client.post(
        LOGIN_URL,
        json={"username": username, "password": password, "client_type": "pc"},
    )
    payload = _assert_success(response, action)
    token = (payload.get("data") or {}).get("access_token")
    assert token, "%s 成功但 data.access_token 为空：%s" % (action, payload)
    client.headers["Authorization"] = "Bearer %s" % token
    return client


@pytest.fixture(scope="module")
def customer_client():
    """登录客户管理账号，账号来源统一配置在 project_information.py。"""
    account = MANAGEMENT_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录管理平台")

    with allure.step("登录管理平台并获取客户管理 Token"):
        client = _login_client(username, password, "登录客户管理账号")
    yield client
    client.headers.pop("Authorization", None)


def _customer_body(name=None, **overrides):
    """生成不调用外部域名服务的合法客户创建请求体。"""
    body = {
        "name": name or "AT-客户管理-%s" % uuid4().hex[:12],
        "deployment_type": "public_cloud",
        "customer_type": "school",
        "manager_name": "接口自动化客户联系人",
        "manager_phone": "13900000000",
        "service_period": 12,
        "valid_start": date.today().isoformat(),
        "valid_end": (date.today() + timedelta(days=365)).isoformat(),
        "dining_limit": 1,
        "pos_count": 1,
        "remarks": "客户管理接口自动化临时数据",
        "attachments": [],
        "call_domain_api": False,
    }
    body.update(overrides)
    return body


def _create_temporary_customer(client, **overrides):
    """创建唯一客户并返回响应对象。"""
    body = _customer_body(**overrides)
    payload = _assert_success(client.post(CUSTOMERS_URL, json=body), "创建临时客户")
    customer = payload["data"]
    _assert_customer_shape(customer, "创建临时客户")
    assert customer["name"] == body["name"], "创建后的客户名称不正确：%s" % customer
    return customer


def _cleanup_temporary_customer(client, customer_id):
    """通过业务删除接口软删除临时客户，避免出现在正常客户列表。"""
    if not customer_id:
        return
    try:
        client.delete("%s/%s" % (CUSTOMERS_URL, customer_id))
    except Exception:
        pass


def _owner_id_for_create(client):
    """从渠道元数据选取负责人，为线索来源渠道构造合法请求体。"""
    payload = _assert_success(client.get(CHANNEL_META_URL), "获取临时渠道创建元数据")
    owners = (payload.get("data") or {}).get("owners") or []
    if not owners:
        pytest.skip("当前环境没有可用负责人，无法创建客户来源渠道")
    owner_id = owners[0].get("id")
    assert isinstance(owner_id, int) and owner_id > 0, "渠道负责人不合法：%s" % owners[0]
    return owner_id


def _create_temporary_channel(client, owner_id):
    """创建合作中临时渠道，供线索转客户来源继承链路使用。"""
    name = "AT-客户来源渠道-%s" % uuid4().hex[:12]
    payload = _assert_success(
        client.post(
            CHANNELS_URL,
            json={
                "name": name,
                "channel_type": "partner",
                "owner_id": owner_id,
                "cooperation_status": "active",
                "start_date": date.today().isoformat(),
                "contact_person": "接口自动化客户来源联系人",
                "contact_phone": "13800000000",
                "channel_cost": "0.00",
                "remark": "客户管理自动化临时来源渠道，可安全删除",
            },
        ),
        "创建临时客户来源渠道",
    )
    channel = payload["data"]
    assert isinstance(channel.get("id"), int) and channel["id"] > 0, "临时渠道 id 非法：%s" % channel
    assert channel.get("name") == name and channel.get("cooperation_status") == "active", channel
    return channel


def _create_temporary_lead(client, channel):
    """创建用于客户来源继承校验的临时线索。"""
    name = "AT-客户来源线索-%s" % uuid4().hex[:12]
    payload = _assert_success(
        client.post(
            LEADS_URL,
            json={
                "name": name,
                "business_type": "education",
                "status": "pending",
                "channel_id": channel["id"],
                "remark": "客户管理来源继承自动化临时线索",
            },
        ),
        "创建客户来源线索",
    )
    lead = payload["data"]
    assert isinstance(lead.get("id"), int) and lead["id"] > 0, "临时线索 id 非法：%s" % lead
    assert lead.get("channel_id") == channel["id"] and lead.get("channel_name") == channel["name"], lead
    return lead


def _cleanup_temporary_lead(client, lead_id):
    """清理临时线索；已转客户时同步删除关联客户。"""
    if not lead_id:
        return
    try:
        client.delete("%s/%s" % (LEADS_URL, lead_id), params={"delete_related_customer": "true"})
    except Exception:
        pass


def _cleanup_temporary_channel(client, channel_id):
    """删除无关联数据的临时来源渠道。"""
    if not channel_id:
        return
    try:
        client.delete("%s/%s" % (CHANNELS_URL, channel_id))
    except Exception:
        pass


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-客户管理")
class Test客户管理查询与校验:
    """认证、列表统计、查询参数与创建模型校验。"""

    @allure.feature("访问权限")
    def test_未登录访问客户列表_返回未授权(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Authorization 请求客户列表"):
            response = anonymous_client.get(CUSTOMERS_URL)
        _assert_error_code(response, "未登录获取客户列表", UNAUTHORIZED_CODE, expected_http_status=401)

    @allure.feature("查询与统计")
    def test_客户列表_分页字段和统计概览完整(self, customer_client):
        with allure.step("查询默认客户列表"):
            payload = _assert_success(
                customer_client.get(CUSTOMERS_URL, params={"page": 1, "page_size": 5}),
                "获取客户列表",
            )
        data = _assert_page_payload(payload, "获取客户列表", expected_page=1, expected_page_size=5)
        stats = data.get("stats")
        assert isinstance(stats, dict), "客户列表缺少统计数据：%s" % data
        assert {"total", "normal", "disabled", "expiring_soon", "expired"} <= set(stats), stats
        assert all(isinstance(value, int) and value >= 0 for value in stats.values()), stats

    @allure.feature("参数校验")
    def test_客户查询与创建_分页必填字段和联系电话校验(self, customer_client):
        with allure.step("使用非法页码查询客户列表"):
            invalid_page_response = customer_client.get(CUSTOMERS_URL, params={"page": 0, "page_size": 10})
        _assert_error_code(invalid_page_response, "客户列表非法页码", INVALID_PARAMS_CODE)

        invalid_bodies = [
            ("缺少全部必填字段", {}),
            (
                "联系电话格式非法",
                {
                    "name": "AT-非法联系电话客户",
                    "deployment_type": "public_cloud",
                    "customer_type": "school",
                    "manager_name": "接口自动化",
                    "manager_phone": "123",
                    "service_period": 12,
                },
            ),
        ]
        for action, body in invalid_bodies:
            with allure.step("创建客户：%s" % action):
                response = customer_client.post(CUSTOMERS_URL, json=body)
            _assert_error_code(response, "创建客户%s" % action, INVALID_PARAMS_CODE)

        with allure.step("查询不存在的客户详情"):
            detail_response = customer_client.get("%s/%s" % (CUSTOMERS_URL, 2147483647))
        _assert_error_code(detail_response, "查询不存在的客户详情", CUSTOMER_NOT_FOUND_CODE)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-客户管理")
class Test客户管理业务链路:
    """客户创建、编辑、续费、状态、密钥、软删除恢复和来源继承链路。"""

    @allure.feature("客户生命周期")
    def test_客户创建_筛选编辑详情与操作日志(self, customer_client):
        _require_write_tests()
        customer_id = None
        try:
            customer = _create_temporary_customer(customer_client)
            customer_id = customer["id"]

            with allure.step("按名称、部署模式和状态组合筛选客户"):
                list_payload = _assert_success(
                    customer_client.get(
                        CUSTOMERS_URL,
                        params={
                            "name": customer["name"],
                            "deployment_type": "public_cloud",
                            "status": "normal",
                            "page": 1,
                            "page_size": 10,
                        },
                    ),
                    "组合筛选客户",
                )
            list_data = _assert_page_payload(list_payload, "组合筛选客户", expected_page=1, expected_page_size=10)
            assert any(item.get("id") == customer_id for item in list_data["items"]), list_data

            updated_name = "AT-客户已编辑-%s" % uuid4().hex[:10]
            with allure.step("更新客户基础信息、配额、域名和附件元数据"):
                update_payload = _assert_success(
                    customer_client.put(
                        "%s/%s" % (CUSTOMERS_URL, customer_id),
                        json={
                            "name": updated_name,
                            "deployment_type": "private_cloud",
                            "customer_type": "enterprise",
                            "manager_name": "接口自动化更新联系人",
                            "manager_phone": "13800000000",
                            "dining_limit": 2,
                            "pos_count": 3,
                            "domain_name": "at-customer.example.invalid",
                            "remarks": "客户标准编辑后的自动化备注",
                            "attachments": [
                                {
                                    "name": "AT-客户资料.txt",
                                    "url": "https://example.com/at-customer.txt",
                                    "size": 12,
                                    "type": "text/plain",
                                }
                            ],
                            "call_domain_api": False,
                        },
                    ),
                    "更新客户",
                )
            updated = update_payload["data"]
            _assert_customer_shape(updated, "更新客户", expected_customer_id=customer_id)
            assert updated["name"] == updated_name, updated
            assert updated["deployment_type"] == "private_cloud", updated
            assert updated["customer_type"] == "enterprise", updated
            assert updated["manager_phone"] == "13800000000", updated
            assert updated["dining_limit"] == 2 and updated["pos_count"] == 3, updated
            assert updated["domain_name"] == "at-customer.example.invalid", updated
            assert len(updated["attachments"]) == 1, updated

            with allure.step("查询编辑后的客户详情和操作日志"):
                detail_payload = _assert_success(
                    customer_client.get("%s/%s" % (CUSTOMERS_URL, customer_id)),
                    "获取客户详情",
                )
                logs_payload = _assert_success(
                    customer_client.get("%s/%s/logs" % (CUSTOMERS_URL, customer_id), params={"page": 1, "page_size": 20}),
                    "获取客户操作日志",
                )
            detail = detail_payload["data"]
            _assert_customer_shape(detail, "获取客户详情", expected_customer_id=customer_id)
            assert detail["name"] == updated_name and detail["is_deleted"] is False, detail
            log_data = _assert_page_payload(logs_payload, "获取客户操作日志", expected_page=1, expected_page_size=20)
            operation_types = {item.get("operation_type") for item in log_data["items"]}
            assert {"create", "update"} <= operation_types, "客户创建和更新日志不完整：%s" % log_data
        finally:
            _cleanup_temporary_customer(customer_client, customer_id)

    @allure.feature("续费与状态")
    def test_客户续费_状态切换应用密钥与操作日志(self, customer_client):
        _require_write_tests()
        customer_id = None
        try:
            customer = _create_temporary_customer(customer_client)
            customer_id = customer["id"]
            renew_start = date.today() + timedelta(days=1)
            renew_end = renew_start + timedelta(days=180)

            with allure.step("为客户续费六个月并更新有效期"):
                renew_payload = _assert_success(
                    customer_client.put(
                        "%s/%s/renew" % (CUSTOMERS_URL, customer_id),
                        json={
                            "service_period": 6,
                            "valid_start": renew_start.isoformat(),
                            "valid_end": renew_end.isoformat(),
                        },
                    ),
                    "客户续费",
                )
            renewed = renew_payload["data"]
            assert renewed.get("service_period") == 18, renewed
            assert str(renewed.get("valid_start")) == renew_start.isoformat(), renewed
            assert str(renewed.get("valid_end")) == renew_end.isoformat(), renewed

            with allure.step("使用非法状态值更新客户应被拒绝"):
                invalid_status_response = customer_client.put(
                    "%s/%s/status" % (CUSTOMERS_URL, customer_id),
                    json={"status": "invalid-status"},
                )
            _assert_error_code(invalid_status_response, "更新客户非法状态", PARAM_ERROR_CODE)

            with allure.step("将客户置为禁用后恢复为正常"):
                disabled_payload = _assert_success(
                    customer_client.put("%s/%s/status" % (CUSTOMERS_URL, customer_id), json={"status": "disabled"}),
                    "禁用客户",
                )
                normal_payload = _assert_success(
                    customer_client.put("%s/%s/status" % (CUSTOMERS_URL, customer_id), json={"status": "normal"}),
                    "恢复客户为正常",
                )
            assert disabled_payload["data"].get("status") == "disabled", disabled_payload
            assert normal_payload["data"].get("status") == "normal", normal_payload

            app_id = "at-app-%s" % uuid4().hex[:12]
            app_secret = "at-secret-%s" % uuid4().hex
            with allure.step("更新临时客户的应用 ID 和应用密钥"):
                secret_payload = _assert_success(
                    customer_client.put(
                        "%s/%s/app-secret" % (CUSTOMERS_URL, customer_id),
                        json={"app_id": app_id, "app_secret": app_secret},
                    ),
                    "更新客户应用密钥",
                )
            assert secret_payload["data"].get("app_id") == app_id, secret_payload
            assert secret_payload["data"].get("app_secret") == app_secret, secret_payload

            logs_payload = _assert_success(
                customer_client.get("%s/%s/logs" % (CUSTOMERS_URL, customer_id), params={"page": 1, "page_size": 30}),
                "获取续费与状态操作日志",
            )
            log_data = _assert_page_payload(logs_payload, "获取续费与状态操作日志", expected_page=1, expected_page_size=30)
            operation_types = {item.get("operation_type") for item in log_data["items"]}
            assert {"create", "renew", "status_change", "app_secret_update"} <= operation_types, log_data
        finally:
            _cleanup_temporary_customer(customer_client, customer_id)

    @allure.feature("删除恢复")
    def test_客户软删除_详情不可见恢复后重新可见(self, customer_client):
        _require_write_tests()
        customer_id = None
        try:
            customer = _create_temporary_customer(customer_client)
            customer_id = customer["id"]

            with allure.step("软删除临时客户"):
                delete_payload = _assert_success(
                    customer_client.delete("%s/%s" % (CUSTOMERS_URL, customer_id)),
                    "删除客户",
                )
            assert delete_payload["data"].get("id") == customer_id, delete_payload

            with allure.step("已删除客户不应出现在详情接口"):
                deleted_detail_response = customer_client.get("%s/%s" % (CUSTOMERS_URL, customer_id))
            _assert_error_code(deleted_detail_response, "查询已删除客户详情", CUSTOMER_NOT_FOUND_CODE)

            with allure.step("恢复已删除客户后重新查询详情"):
                restore_payload = _assert_success(
                    customer_client.post("%s/%s/restore" % (CUSTOMERS_URL, customer_id)),
                    "恢复已删除客户",
                )
                detail_payload = _assert_success(
                    customer_client.get("%s/%s" % (CUSTOMERS_URL, customer_id)),
                    "查询已恢复客户详情",
                )
            assert restore_payload["data"].get("id") == customer_id, restore_payload
            assert detail_payload["data"].get("is_deleted") is False, detail_payload

            logs_payload = _assert_success(
                customer_client.get("%s/%s/logs" % (CUSTOMERS_URL, customer_id), params={"page": 1, "page_size": 20}),
                "获取删除恢复操作日志",
            )
            log_data = _assert_page_payload(logs_payload, "获取删除恢复操作日志", expected_page=1, expected_page_size=20)
            operation_types = {item.get("operation_type") for item in log_data["items"]}
            assert {"create", "delete", "restore"} <= operation_types, log_data
        finally:
            _cleanup_temporary_customer(customer_client, customer_id)

    @allure.feature("名称唯一性")
    def test_客户名称_正常客户名称不可重复(self, customer_client):
        _require_write_tests()
        customer_id = None
        try:
            name = "AT-客户重名-%s" % uuid4().hex[:12]
            customer = _create_temporary_customer(customer_client, name=name)
            customer_id = customer["id"]
            with allure.step("使用相同名称再次创建客户"):
                duplicate_response = customer_client.post(CUSTOMERS_URL, json=_customer_body(name=name))
            _assert_error_code(duplicate_response, "创建同名客户", NAME_ALREADY_EXISTS_CODE)
        finally:
            _cleanup_temporary_customer(customer_client, customer_id)

    @allure.feature("线索来源继承")
    def test_线索转客户_继承来源渠道且普通编辑不可篡改(self, customer_client):
        _require_write_tests()
        channel_id = None
        lead_id = None
        customer_id = None
        try:
            owner_id = _owner_id_for_create(customer_client)
            channel = _create_temporary_channel(customer_client, owner_id)
            channel_id = channel["id"]
            lead = _create_temporary_lead(customer_client, channel)
            lead_id = lead["id"]

            with allure.step("通过客户创建接口关联来源线索"):
                customer = _create_temporary_customer(customer_client, lead_id=lead_id)
            customer_id = customer["id"]
            assert customer.get("lead_id") == lead_id, "客户未关联来源线索：%s" % customer
            assert customer.get("channel_id") == channel_id, "客户未继承来源渠道 id：%s" % customer
            assert customer.get("channel_name") == channel["name"], "客户未继承来源渠道名称：%s" % customer

            with allure.step("线索应自动变为已转化"):
                lead_payload = _assert_success(
                    customer_client.get("%s/%s" % (LEADS_URL, lead_id)),
                    "查询已转化来源线索",
                )
            assert lead_payload["data"].get("status") == "converted", lead_payload

            with allure.step("普通编辑携带其他来源渠道字段不应改变来源"):
                update_payload = _assert_success(
                    customer_client.put(
                        "%s/%s" % (CUSTOMERS_URL, customer_id),
                        json={
                            "channel_id": 2147483647,
                            "channel_name": "AT-不应写入的来源渠道",
                            "channel_contact": "不应写入",
                            "channel_phone": "13700000000",
                            "remarks": "验证客户来源渠道只读",
                        },
                    ),
                    "更新客户来源字段",
                )
            updated = update_payload["data"]
            assert updated.get("channel_id") == channel_id, "普通编辑不应改变来源渠道 id：%s" % updated
            assert updated.get("channel_name") == channel["name"], "普通编辑不应改变来源渠道名称：%s" % updated
            assert updated.get("lead_id") == lead_id, "普通编辑不应改变来源线索：%s" % updated

            with allure.step("按来源线索和渠道筛选客户"):
                list_payload = _assert_success(
                    customer_client.get(
                        CUSTOMERS_URL,
                        params={"lead_id": lead_id, "channel_id": channel_id, "page": 1, "page_size": 10},
                    ),
                    "按来源线索和渠道筛选客户",
                )
            list_data = _assert_page_payload(list_payload, "按来源线索和渠道筛选客户", expected_page=1, expected_page_size=10)
            assert any(item.get("id") == customer_id for item in list_data["items"]), list_data
        finally:
            _cleanup_temporary_customer(customer_client, customer_id)
            _cleanup_temporary_lead(customer_client, lead_id)
            _cleanup_temporary_channel(customer_client, channel_id)
