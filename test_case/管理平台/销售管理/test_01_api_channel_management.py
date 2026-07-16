# -*- coding: utf-8 -*-
"""管理平台销售管理-渠道管理接口自动化测试。

被测服务的接口前缀为 ``/v1``，统一响应格式为：
``{"code": 20000, "msg": "...", "data": ...}``。

测试环境、请求头和具备渠道管理权限的账号统一配置在
``config/project_information.py``，本脚本直接使用该配置。

写操作开关 ``ENABLE_WRITE_TESTS`` 也在该配置文件中维护。启用时会执行
创建、更新、失效、删除及渠道 -> 线索 -> 客户的集成链路；所有写入数据使用
唯一名称，并在 finally 中尝试清理。
"""
from datetime import date
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, MANAGEMENT_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
CHANNELS_URL = "/v1/channels"
CHANNEL_OPTIONS_URL = "/v1/channels/options"
CHANNEL_META_URL = "/v1/channels/meta"
CHANNEL_SUMMARY_URL = "/v1/channels/summary"
CHANNEL_SEARCH_URL = "/v1/channels/search"
LEADS_URL = "/v1/leads"
CUSTOMERS_URL = "/v1/customers"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
PARAM_INVALID_CODE = 4102
FORBIDDEN_CODE = 4030
CHANNEL_NOT_FOUND_CODE = 5400
CHANNEL_STATUS_NOT_ALLOWED_CODE = 5401
CHANNEL_DELETE_CONFLICT_CODE = 5402
TOKEN_INVALID_CODE = 5104

CHANNEL_TYPES = {
    "advertising",
    "partner",
    "offline_event",
    "referral",
    "organic",
    "telemarketing",
    "ground_promotion",
    "other",
}
COOPERATION_STATUSES = {"not_started", "active", "paused", "ended", "invalid"}
CHANNEL_REQUIRED_FIELDS = {
    "id",
    "name",
    "channel_type",
    "owner_id",
    "cooperation_status",
    "start_date",
    "is_sales_managed",
    "is_deleted",
    "lead_count",
    "customer_count",
    "converted_lead_count",
}


def _write_tests_enabled():
    return ENABLE_WRITE_TESTS


def _require_write_tests():
    if not _write_tests_enabled():
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _parse_json(response, action):
    """将响应转换为 JSON，失败时附带请求地址与响应片段便于定位。"""
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
    """校验管理平台统一成功响应；无模块权限时明确标记为跳过。"""
    assert response.status_code == 200, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = _parse_json(response, action)
    if payload.get("code") == FORBIDDEN_CODE:
        pytest.skip("登录账号缺少 menu:sales-channel 或 permission:manage 权限")
    assert payload.get("code") == SUCCESS_CODE, "%s 业务失败：%s" % (action, payload)
    assert "data" in payload, "%s 成功响应缺少 data：%s" % (action, payload)
    return payload


def _assert_page_payload(payload, action, expected_page=None, expected_page_size=None):
    """校验列表接口的分页外壳和基本字段。"""
    data = payload["data"]
    assert isinstance(data, dict), "%s data 应为分页对象，实际为 %r" % (action, data)
    assert isinstance(data.get("items"), list), "%s data.items 应为数组：%s" % (action, data)
    assert isinstance(data.get("total"), int), "%s data.total 应为整数：%s" % (action, data)
    assert isinstance(data.get("page"), int), "%s data.page 应为整数：%s" % (action, data)
    assert isinstance(data.get("page_size"), int), "%s data.page_size 应为整数：%s" % (action, data)
    assert isinstance(data.get("total_pages"), int), "%s data.total_pages 应为整数：%s" % (action, data)
    if expected_page is not None:
        assert data["page"] == expected_page, "%s 页码回显不正确：%s" % (action, data)
    if expected_page_size is not None:
        assert data["page_size"] == expected_page_size, "%s 每页数量回显不正确：%s" % (action, data)
    assert len(data["items"]) <= data["page_size"], "%s 返回条数超过 page_size：%s" % (action, data)
    return data


def _assert_channel_shape(channel, action):
    """校验渠道列表和详情共用的数据结构。"""
    assert isinstance(channel, dict), "%s 渠道项应为对象，实际为 %r" % (action, channel)
    missing_fields = CHANNEL_REQUIRED_FIELDS - set(channel)
    assert not missing_fields, "%s 渠道项缺少字段：%s；实际=%s" % (action, missing_fields, channel)
    assert isinstance(channel["id"], int) and channel["id"] > 0, "%s 渠道 id 非法：%s" % (action, channel)
    assert isinstance(channel["name"], str) and channel["name"].strip(), "%s 渠道名称为空：%s" % (action, channel)
    assert channel["channel_type"] in CHANNEL_TYPES, "%s 渠道类型异常：%s" % (action, channel)
    assert channel["cooperation_status"] in COOPERATION_STATUSES, "%s 合作状态异常：%s" % (action, channel)
    assert channel["is_sales_managed"] is True, "%s 返回了非销售渠道管理数据：%s" % (action, channel)
    assert channel["is_deleted"] is False, "%s 默认列表不应返回已删除渠道：%s" % (action, channel)


def _first_channel(client):
    """获取一条可见渠道，供详情、搜索和关联数据接口复用。"""
    response = client.get(CHANNELS_URL, params={"page": 1, "page_size": 1})
    payload = _assert_success(response, "获取渠道列表（取样）")
    data = _assert_page_payload(payload, "获取渠道列表（取样）", expected_page=1, expected_page_size=1)
    return data["items"][0] if data["items"] else None


def _login_client(username, password, action):
    """登录指定内部账号，返回携带 Bearer Token 的专用客户端。"""
    client = HttpClient(
        headers=default_headers.copy(),
    )
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
def channel_client():
    """登录管理平台并返回只供本模块使用的具备渠道管理权限的客户端。"""
    account = MANAGEMENT_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip(
            "未配置 MANAGEMENT_TEST_ACCOUNT，无法登录管理平台"
        )

    with allure.step("登录管理平台并获取渠道管理 Token"):
        client = _login_client(username, password, "登录管理平台")

    yield client
    client.headers.pop("Authorization", None)
def _owner_id_for_create(client):
    """从渠道元数据中选取一名有效负责人，避免在用例中写死用户 ID。"""
    payload = _assert_success(client.get(CHANNEL_META_URL), "获取创建渠道所需元数据")
    owners = (payload.get("data") or {}).get("owners") or []
    if not owners:
        pytest.skip("当前环境没有可用负责人，无法构造合法渠道创建请求")
    owner_id = owners[0].get("id")
    assert isinstance(owner_id, int) and owner_id > 0, "渠道元数据中的负责人不合法：%s" % owners[0]
    return owner_id


def _channel_body(owner_id, name, status="active", **overrides):
    """生成一个满足后端 ChannelCreate 模型的基础请求体。"""
    body = {
        "name": name,
        "channel_type": "partner",
        "owner_id": owner_id,
        "cooperation_status": status,
        "start_date": date.today().isoformat(),
        "contact_person": "接口自动化",
        "contact_phone": "13800000000",
        "channel_cost": "0.00",
        "remark": "接口自动化临时数据，可安全删除",
    }
    body.update(overrides)
    return body


def _create_temporary_channel(client, owner_id, status="active", **overrides):
    """创建唯一名称的渠道，并返回完整渠道对象。"""
    name = "AT-渠道管理-%s" % uuid4().hex[:12]
    body = _channel_body(owner_id, name, status=status, **overrides)
    payload = _assert_success(client.post(CHANNELS_URL, json=body), "创建临时渠道")
    channel = payload["data"]
    _assert_channel_shape(channel, "创建临时渠道")
    assert channel["name"] == name, "创建后的渠道名称不正确：%s" % channel
    return channel


def _cleanup_temporary_lead(client, lead_id):
    """删除临时线索及其关联客户；失败时不掩盖主断言的异常。"""
    if not lead_id:
        return
    try:
        client.delete("%s/%s" % (LEADS_URL, lead_id), params={"delete_related_customer": "true"})
    except Exception:
        pass


def _cleanup_temporary_channel(client, channel_id):
    """删除无关联数据的临时渠道。"""
    if not channel_id:
        return
    try:
        client.delete("%s/%s" % (CHANNELS_URL, channel_id))
    except Exception:
        pass


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-渠道管理")
class Test渠道管理权限与校验:
    """校验认证、模块权限与后端请求模型，均不创建业务数据。"""

    @allure.feature("访问权限")
    def test_未登录访问渠道列表_返回令牌无效(self):
        anonymous_client = HttpClient(
            headers=default_headers.copy(),
        )
        with allure.step("不携带 Authorization 请求渠道列表"):
            response = anonymous_client.get(CHANNELS_URL)
        assert response.status_code == 200, "统一鉴权异常应使用 HTTP 200：%s" % response.text
        payload = _parse_json(response, "未登录获取渠道列表")
        assert payload.get("code") == TOKEN_INVALID_CODE, "未登录访问应返回令牌无效：%s" % payload

    @allure.feature("新增渠道校验")
    def test_新增渠道_缺少必填字段被拒绝(self, channel_client):
        with allure.step("提交空请求体"):
            response = channel_client.post(CHANNELS_URL, json={})
        assert response.status_code == 200, "参数校验异常应使用 HTTP 200：%s" % response.text
        payload = _parse_json(response, "新增渠道缺少必填字段")
        assert payload.get("code") == INVALID_PARAMS_CODE, "缺少必填字段应返回 4001：%s" % payload
        assert isinstance(payload.get("data"), list) and payload["data"], "应返回字段错误详情：%s" % payload

    @allure.feature("新增渠道校验")
    def test_新增渠道_字段格式与边界校验(self, channel_client):
        owner_id = _owner_id_for_create(channel_client)
        invalid_cases = [
            ("名称超过200字符", {"name": "a" * 201}),
            ("渠道类型非法", {"channel_type": "unsupported_type"}),
            ("合作状态非法", {"cooperation_status": "unsupported_status"}),
            ("联系方式非法", {"contact_phone": "not-a-phone"}),
            ("结束时间早于开始时间", {"start_date": "2026-07-02", "end_date": "2026-07-01"}),
            ("渠道成本超过两位小数", {"channel_cost": "1.001"}),
            ("备注超过500字符", {"remark": "a" * 501}),
        ]
        for case_name, overrides in invalid_cases:
            with allure.step("校验%s" % case_name):
                body = _channel_body(owner_id, "AT-非法-%s" % uuid4().hex[:8])
                body.update(overrides)
                response = channel_client.post(CHANNELS_URL, json=body)
            assert response.status_code == 200, "%s 的 HTTP 状态异常：%s" % (case_name, response.text)
            payload = _parse_json(response, "新增渠道%s" % case_name)
            assert payload.get("code") == INVALID_PARAMS_CODE, "%s 应返回 4001：%s" % (case_name, payload)

    @allure.feature("渠道更新")
    def test_更新不存在渠道_返回业务错误码(self, channel_client):
        with allure.step("更新不存在的渠道"):
            response = channel_client.put("%s/%s" % (CHANNELS_URL, 2147483647), json={"remark": "不存在"})
        assert response.status_code == 200, "业务异常应使用 HTTP 200：%s" % response.text
        payload = _parse_json(response, "更新不存在渠道")
        assert payload.get("code") == CHANNEL_NOT_FOUND_CODE, "更新不存在渠道应返回 5400：%s" % payload


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-渠道管理")
class Test渠道管理查询接口:
    """不改变被测环境数据的渠道管理接口。"""

    @allure.feature("渠道枚举元数据")
    def test_渠道元数据_返回固定枚举和负责人(self, channel_client):
        with allure.step("获取渠道类型、合作状态与可选负责人"):
            payload = _assert_success(channel_client.get(CHANNEL_META_URL), "获取渠道枚举元数据")
        data = payload["data"]
        assert isinstance(data, dict), "渠道元数据 data 应为对象：%s" % payload
        channel_types = data.get("channel_types")
        statuses = data.get("cooperation_statuses")
        owners = data.get("owners")
        assert isinstance(channel_types, list), "channel_types 应为数组：%s" % data
        assert isinstance(statuses, list), "cooperation_statuses 应为数组：%s" % data
        assert isinstance(owners, list), "owners 应为数组：%s" % data
        assert {item.get("value") for item in channel_types} == CHANNEL_TYPES
        assert {item.get("value") for item in statuses} == COOPERATION_STATUSES
        for owner in owners:
            assert isinstance(owner.get("id"), int) and owner["id"] > 0, "负责人 id 非法：%s" % owner

    @allure.feature("渠道列表")
    def test_渠道列表_默认分页和字段完整(self, channel_client):
        with allure.step("按默认分页获取渠道列表"):
            payload = _assert_success(
                channel_client.get(CHANNELS_URL, params={"page": 1, "page_size": 10}),
                "获取渠道列表",
            )
        data = _assert_page_payload(payload, "获取渠道列表", expected_page=1, expected_page_size=10)
        for channel in data["items"]:
            _assert_channel_shape(channel, "获取渠道列表")

    @allure.feature("渠道列表")
    def test_渠道列表_多选类型和状态筛选(self, channel_client):
        params = {
            "channel_type": "partner,offline_event",
            "cooperation_status": "active,paused",
            "page": 1,
            "page_size": 20,
        }
        with allure.step("按渠道类型和合作状态组合筛选"):
            payload = _assert_success(channel_client.get(CHANNELS_URL, params=params), "渠道组合筛选")
        data = _assert_page_payload(payload, "渠道组合筛选", expected_page=1, expected_page_size=20)
        for channel in data["items"]:
            _assert_channel_shape(channel, "渠道组合筛选")
            assert channel["channel_type"] in {"partner", "offline_event"}
            assert channel["cooperation_status"] in {"active", "paused"}

    @allure.feature("渠道列表")
    def test_渠道列表_非法分页参数被拒绝(self, channel_client):
        with allure.step("传入不合法页码 page=0"):
            response = channel_client.get(CHANNELS_URL, params={"page": 0, "page_size": 10})
        assert response.status_code == 200, "统一错误响应的 HTTP 状态应为 200：%s" % response.text
        payload = _parse_json(response, "渠道列表非法分页")
        assert payload.get("code") == INVALID_PARAMS_CODE, "非法分页应返回参数校验错误：%s" % payload
        assert isinstance(payload.get("data"), list), "参数校验错误应返回错误详情：%s" % payload

    @allure.feature("渠道下拉选项")
    def test_渠道选项_默认仅返回合作中渠道(self, channel_client):
        with allure.step("获取默认渠道下拉选项"):
            payload = _assert_success(channel_client.get(CHANNEL_OPTIONS_URL), "获取渠道下拉选项")
        options = payload["data"]
        assert isinstance(options, list), "渠道选项 data 应为数组：%s" % payload
        for option in options:
            assert isinstance(option.get("id"), int) and option["id"] > 0, "渠道选项 id 非法：%s" % option
            assert option.get("cooperation_status") == "active", "默认选项不应包含非合作中渠道：%s" % option

    @allure.feature("渠道汇总统计")
    def test_渠道汇总_返回统计和近七日趋势(self, channel_client):
        with allure.step("获取渠道汇总统计"):
            payload = _assert_success(channel_client.get(CHANNEL_SUMMARY_URL), "获取渠道汇总统计")
        summary = payload["data"]
        required_fields = {
            "total_channels",
            "active_channels",
            "status_counts",
            "total_leads",
            "total_customers",
            "total_converted_leads",
            "total_cost",
            "trend",
        }
        assert isinstance(summary, dict), "渠道汇总 data 应为对象：%s" % payload
        assert required_fields <= set(summary), "渠道汇总缺少字段：%s" % summary
        assert isinstance(summary["status_counts"], dict), "status_counts 应为对象：%s" % summary
        assert COOPERATION_STATUSES <= set(summary["status_counts"]), "合作状态统计不完整：%s" % summary
        trend = summary["trend"]
        assert isinstance(trend, dict), "trend 应为对象：%s" % summary
        for key in (
            "days",
            "channel_counts",
            "active_rates",
            "lead_counts",
            "customer_counts",
            "converted_lead_counts",
            "conversion_rates",
            "cost_amounts",
        ):
            assert isinstance(trend.get(key), list) and len(trend[key]) == 7, "趋势字段 %s 应包含 7 天数据：%s" % (key, trend)

    @allure.feature("渠道详情")
    def test_渠道详情_关联线索客户日志(self, channel_client):
        channel = _first_channel(channel_client)
        if channel is None:
            pytest.skip("当前环境没有销售渠道管理数据，无法验证详情与关联数据接口")
        channel_id = channel["id"]

        with allure.step("获取渠道详情"):
            detail_payload = _assert_success(channel_client.get("%s/%s" % (CHANNELS_URL, channel_id)), "获取渠道详情")
        detail = detail_payload["data"]
        _assert_channel_shape(detail, "获取渠道详情")
        assert detail["id"] == channel_id, "详情返回渠道与列表取样不一致：%s" % detail

        for suffix, label in (("leads", "关联线索"), ("customers", "关联客户"), ("logs", "操作日志")):
            with allure.step("获取渠道%s" % label):
                payload = _assert_success(
                    channel_client.get("%s/%s/%s" % (CHANNELS_URL, channel_id, suffix)),
                    "获取渠道%s" % label,
                )
            _assert_page_payload(payload, "获取渠道%s" % label, expected_page=1)

    @allure.feature("渠道搜索")
    def test_渠道搜索_名称命中返回对应渠道(self, channel_client):
        channel = _first_channel(channel_client)
        if channel is None:
            pytest.skip("当前环境没有销售渠道管理数据，无法验证名称搜索")
        keyword = channel["name"].strip()[: min(3, len(channel["name"].strip()))]
        with allure.step("按列表中渠道名称关键字搜索"):
            payload = _assert_success(
                channel_client.get(CHANNEL_SEARCH_URL, params={"name": keyword, "limit": 20}),
                "渠道名称搜索",
            )
        data = _assert_page_payload(payload, "渠道名称搜索", expected_page=1, expected_page_size=20)
        assert any(item.get("id") == channel["id"] for item in data["items"]), (
            "搜索结果未包含原渠道。keyword=%s, channel=%s, result=%s" % (keyword, channel, data)
        )

    @allure.feature("渠道详情")
    def test_渠道详情_不存在渠道返回业务错误码(self, channel_client):
        with allure.step("查询不存在的渠道"):
            response = channel_client.get("%s/%s" % (CHANNELS_URL, 2147483647))
        assert response.status_code == 200, "业务异常应使用统一 HTTP 200 响应：%s" % response.text
        payload = _parse_json(response, "查询不存在渠道")
        assert payload.get("code") == CHANNEL_NOT_FOUND_CODE, "不存在渠道应返回 5400：%s" % payload


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-渠道管理")
class Test渠道管理写操作:
    """需显式授权才执行的写操作链路，避免污染日常回归环境。"""

    @allure.feature("渠道创建、更新、失效与删除")
    def test_渠道生命周期_创建更新失效删除(self, channel_client):
        _require_write_tests()

        meta_payload = _assert_success(channel_client.get(CHANNEL_META_URL), "获取创建渠道所需元数据")
        owners = (meta_payload.get("data") or {}).get("owners") or []
        if not owners:
            pytest.skip("当前环境没有可用负责人，无法构造合法渠道创建请求")

        channel_name = "AT-渠道管理-%s" % uuid4().hex[:12]
        create_body = {
            "name": channel_name,
            "channel_type": "partner",
            "owner_id": owners[0]["id"],
            "cooperation_status": "active",
            "start_date": date.today().isoformat(),
            "contact_person": "接口自动化",
            "contact_phone": "13800000000",
            "channel_cost": "0.00",
            "remark": "接口自动化临时数据，可安全删除",
        }
        created_channel_id = None
        deleted = False
        try:
            with allure.step("创建唯一标识的临时渠道"):
                create_payload = _assert_success(
                    channel_client.post(CHANNELS_URL, json=create_body),
                    "创建渠道",
                )
            created = create_payload["data"]
            _assert_channel_shape(created, "创建渠道")
            created_channel_id = created["id"]
            assert created["name"] == channel_name, "创建后的渠道名称不正确：%s" % created

            with allure.step("更新临时渠道备注"):
                update_payload = _assert_success(
                    channel_client.put(
                        "%s/%s" % (CHANNELS_URL, created_channel_id),
                        json={"remark": "接口自动化更新后的临时备注"},
                    ),
                    "更新渠道",
                )
            assert update_payload["data"]["remark"] == "接口自动化更新后的临时备注"

            with allure.step("将临时渠道置为已失效"):
                invalidate_payload = _assert_success(
                    channel_client.post("%s/%s/invalidate" % (CHANNELS_URL, created_channel_id), json={}),
                    "置渠道为已失效",
                )
            assert invalidate_payload["data"]["cooperation_status"] == "invalid"

            with allure.step("删除无关联数据的临时渠道"):
                _assert_success(
                    channel_client.delete("%s/%s" % (CHANNELS_URL, created_channel_id)),
                    "删除临时渠道",
                )
            deleted = True

            with allure.step("确认已删除渠道不再可被默认详情查询"):
                detail_payload = _parse_json(
                    channel_client.get("%s/%s" % (CHANNELS_URL, created_channel_id)),
                    "确认删除结果",
                )
            assert detail_payload.get("code") == CHANNEL_NOT_FOUND_CODE, "删除后渠道仍可查询：%s" % detail_payload
        finally:
            # 用例中途失败时仍尽力回收临时数据，避免污染后续回归环境。
            if created_channel_id and not deleted:
                try:
                    channel_client.delete("%s/%s" % (CHANNELS_URL, created_channel_id))
                except Exception:
                    pass

    @allure.feature("渠道筛选与软删除")
    def test_渠道筛选_名称联系人负责人和已删除可见性(self, channel_client):
        _require_write_tests()
        channel_id = None
        try:
            owner_id = _owner_id_for_create(channel_client)
            contact_person = "AT联系人%s" % uuid4().hex[:8]
            channel = _create_temporary_channel(
                channel_client,
                owner_id,
                status="paused",
                channel_type="offline_event",
                contact_person=contact_person,
            )
            channel_id = channel["id"]

            filter_cases = [
                ("名称", {"name": channel["name"]}),
                ("联系人", {"contact_person": contact_person}),
                ("负责人", {"owner_id": str(owner_id)}),
                ("类型和状态", {"channel_type": "offline_event", "cooperation_status": "paused"}),
            ]
            for label, params in filter_cases:
                with allure.step("按%s筛选临时渠道" % label):
                    params.update({"page": 1, "page_size": 20})
                    payload = _assert_success(channel_client.get(CHANNELS_URL, params=params), "渠道%s筛选" % label)
                data = _assert_page_payload(payload, "渠道%s筛选" % label, expected_page=1, expected_page_size=20)
                assert any(item.get("id") == channel_id for item in data["items"]), (
                    "%s筛选未命中临时渠道：%s" % (label, data)
                )

            with allure.step("软删除临时渠道"):
                _assert_success(channel_client.delete("%s/%s" % (CHANNELS_URL, channel_id)), "删除筛选临时渠道")

            with allure.step("默认列表不应包含已删除渠道"):
                default_payload = _assert_success(
                    channel_client.get(CHANNELS_URL, params={"name": channel["name"], "page": 1, "page_size": 20}),
                    "查询默认渠道列表",
                )
            default_data = _assert_page_payload(default_payload, "查询默认渠道列表", expected_page=1, expected_page_size=20)
            assert all(item.get("id") != channel_id for item in default_data["items"]), default_data

            with allure.step("include_deleted=true 应查询到已删除渠道"):
                deleted_payload = _assert_success(
                    channel_client.get(
                        CHANNELS_URL,
                        params={"name": channel["name"], "include_deleted": "true", "page": 1, "page_size": 20},
                    ),
                    "查询含已删除渠道列表",
                )
            deleted_data = _assert_page_payload(deleted_payload, "查询含已删除渠道列表", expected_page=1, expected_page_size=20)
            deleted_item = next((item for item in deleted_data["items"] if item.get("id") == channel_id), None)
            assert deleted_item and deleted_item.get("is_deleted") is True, "已删除渠道查询结果不正确：%s" % deleted_data
            channel_id = None
        finally:
            _cleanup_temporary_channel(channel_client, channel_id)

    @allure.feature("渠道更新校验")
    def test_渠道更新_结束时间早于开始时间被拒绝(self, channel_client):
        _require_write_tests()
        channel_id = None
        try:
            channel = _create_temporary_channel(channel_client, _owner_id_for_create(channel_client))
            channel_id = channel["id"]
            with allure.step("更新结束时间为开始时间之前"):
                response = channel_client.put(
                    "%s/%s" % (CHANNELS_URL, channel_id),
                    json={"end_date": "2000-01-01"},
                )
            assert response.status_code == 200, "统一业务异常应使用 HTTP 200：%s" % response.text
            payload = _parse_json(response, "更新渠道日期范围")
            assert payload.get("code") == PARAM_INVALID_CODE, "日期范围非法应返回 4102：%s" % payload
        finally:
            _cleanup_temporary_channel(channel_client, channel_id)

    @allure.feature("渠道状态限制")
    def test_非合作中渠道_不可作为新线索来源(self, channel_client):
        _require_write_tests()
        owner_id = _owner_id_for_create(channel_client)
        for status in ("not_started", "paused", "ended", "invalid"):
            channel_id = None
            try:
                channel = _create_temporary_channel(channel_client, owner_id, status=status)
                channel_id = channel["id"]
                lead_body = {
                    "name": "AT-受限线索-%s" % uuid4().hex[:10],
                    "business_type": "education",
                    "status": "pending",
                    "channel_id": channel_id,
                }
                with allure.step("使用%s渠道创建线索" % status):
                    response = channel_client.post(LEADS_URL, json=lead_body)
                assert response.status_code == 200, "%s 状态校验 HTTP 异常：%s" % (status, response.text)
                payload = _parse_json(response, "%s渠道创建线索" % status)
                assert payload.get("code") == CHANNEL_STATUS_NOT_ALLOWED_CODE, (
                    "%s渠道不应允许创建线索：%s" % (status, payload)
                )
                with allure.step("按%s状态筛选应命中该渠道" % status):
                    list_payload = _assert_success(
                        channel_client.get(
                            CHANNELS_URL,
                            params={"cooperation_status": status, "name": channel["name"], "page": 1, "page_size": 10},
                        ),
                        "%s状态渠道筛选" % status,
                    )
                list_data = _assert_page_payload(list_payload, "%s状态渠道筛选" % status, expected_page=1, expected_page_size=10)
                assert any(item.get("id") == channel_id for item in list_data["items"]), list_data
            finally:
                _cleanup_temporary_channel(channel_client, channel_id)

    @allure.feature("渠道-线索-客户闭环")
    def test_渠道到线索再到客户_统计日志删除保护与失效限制(self, channel_client):
        _require_write_tests()
        channel_id = None
        lead_id = None
        replacement_channel_id = None
        try:
            owner_id = _owner_id_for_create(channel_client)
            channel = _create_temporary_channel(
                channel_client,
                owner_id,
                status="active",
                channel_cost="100.00",
                contact_person="接口自动化渠道联系人",
            )
            channel_id = channel["id"]

            with allure.step("合作中临时渠道应出现在默认下拉选项"):
                options_payload = _assert_success(channel_client.get(CHANNEL_OPTIONS_URL), "获取合作中渠道选项")
            assert any(item.get("id") == channel_id for item in options_payload["data"]), options_payload

            lead_body = {
                "name": "AT-渠道线索-%s" % uuid4().hex[:10],
                "business_type": "education",
                "status": "pending",
                "channel_id": channel_id,
                "remark": "由渠道管理集成测试创建",
            }
            with allure.step("通过合作中渠道创建线索"):
                lead_payload = _assert_success(channel_client.post(LEADS_URL, json=lead_body), "创建渠道线索")
            lead = lead_payload["data"]
            lead_id = lead.get("id")
            assert isinstance(lead_id, int) and lead_id > 0, "创建线索未返回 id：%s" % lead
            assert lead.get("channel_id") == channel_id, "线索未继承渠道 id：%s" % lead
            assert lead.get("channel_name") == channel["name"], "线索未继承渠道名称：%s" % lead
            assert lead.get("channel_contact") == channel["contact_person"], "线索未继承渠道联系人：%s" % lead

            with allure.step("验证渠道详情和关联线索统计已刷新"):
                detail_payload = _assert_success(
                    channel_client.get("%s/%s" % (CHANNELS_URL, channel_id)),
                    "获取含线索的渠道详情",
                )
                leads_payload = _assert_success(
                    channel_client.get("%s/%s/leads" % (CHANNELS_URL, channel_id)),
                    "获取渠道关联线索",
                )
            assert detail_payload["data"]["lead_count"] == 1, detail_payload
            leads_data = _assert_page_payload(leads_payload, "获取渠道关联线索", expected_page=1)
            assert any(item.get("id") == lead_id for item in leads_data["items"]), leads_data

            customer_body = {
                "name": "AT-渠道客户-%s" % uuid4().hex[:10],
                "deployment_type": "saas",
                "customer_type": "school",
                "manager_name": "接口自动化客户联系人",
                "manager_phone": "13900000000",
                "service_period": 12,
                "remarks": "由渠道管理集成测试转化",
            }
            with allure.step("将渠道线索转化为客户"):
                convert_payload = _assert_success(
                    channel_client.post("%s/%s/convert-to-customer" % (LEADS_URL, lead_id), json=customer_body),
                    "线索转客户",
                )
            converted_lead = convert_payload["data"].get("lead") or {}
            customer = convert_payload["data"].get("customer") or {}
            customer_id = customer.get("id")
            assert customer_id, "线索转客户未返回客户数据：%s" % convert_payload
            assert converted_lead.get("status") == "converted", "线索状态未更新为 converted：%s" % converted_lead
            assert customer.get("channel_id") == channel_id, "客户未继承渠道 id：%s" % customer
            assert customer.get("channel_name") == channel["name"], "客户未继承渠道名称：%s" % customer
            assert customer.get("lead_id") == lead_id, "客户未关联来源线索：%s" % customer

            with allure.step("客户普通更新不能篡改继承的来源渠道"):
                replacement_channel = _create_temporary_channel(channel_client, owner_id, status="active")
                replacement_channel_id = replacement_channel["id"]
                customer_update_payload = _assert_success(
                    channel_client.put(
                        "%s/%s" % (CUSTOMERS_URL, customer_id),
                        json={
                            "channel_id": replacement_channel_id,
                            "channel_name": replacement_channel["name"],
                            "remarks": "验证来源渠道只读",
                        },
                    ),
                    "更新客户来源渠道",
                )
            updated_customer = customer_update_payload["data"]
            assert updated_customer.get("channel_id") == channel_id, "客户更新不应改变来源渠道：%s" % updated_customer
            assert updated_customer.get("channel_name") == channel["name"], "客户更新不应改变来源渠道名称：%s" % updated_customer

            with allure.step("验证关联客户、统计与渠道操作日志"):
                customers_payload = _assert_success(
                    channel_client.get("%s/%s/customers" % (CHANNELS_URL, channel_id)),
                    "获取渠道关联客户",
                )
                refreshed_detail = _assert_success(
                    channel_client.get("%s/%s" % (CHANNELS_URL, channel_id)),
                    "获取转化后的渠道详情",
                )
                logs_payload = _assert_success(
                    channel_client.get("%s/%s/logs" % (CHANNELS_URL, channel_id)),
                    "获取渠道操作日志",
                )
            customers_data = _assert_page_payload(customers_payload, "获取渠道关联客户", expected_page=1)
            assert any(item.get("id") == customer_id for item in customers_data["items"]), customers_data
            stats = refreshed_detail["data"]
            assert stats["lead_count"] == 1 and stats["customer_count"] == 1, stats
            assert stats["converted_lead_count"] == 1 and float(stats["conversion_rate"]) == 100.0, stats
            assert float(stats["cost_per_lead"]) == 100.0 and float(stats["cost_per_customer"]) == 100.0, stats
            logs_data = _assert_page_payload(logs_payload, "获取渠道操作日志", expected_page=1)
            actions = {item.get("action") for item in logs_data["items"]}
            assert {"create", "create_lead", "lead_convert"} <= actions, "渠道日志不完整：%s" % logs_data

            with allure.step("已关联线索和客户的渠道删除应被保护"):
                delete_response = channel_client.delete("%s/%s" % (CHANNELS_URL, channel_id))
            delete_payload = _parse_json(delete_response, "删除已关联渠道")
            assert delete_payload.get("code") == CHANNEL_DELETE_CONFLICT_CODE, "已关联渠道删除应返回 5402：%s" % delete_payload
            counts = delete_payload.get("data") or {}
            assert counts.get("lead_count", 0) >= 1 and counts.get("customer_count", 0) >= 1, counts

            with allure.step("置为失效后渠道不应继续作为线索来源"):
                invalid_payload = _assert_success(
                    channel_client.post("%s/%s/invalidate" % (CHANNELS_URL, channel_id), json={}),
                    "置关联渠道为失效",
                )
                forbidden_lead_response = channel_client.post(
                    LEADS_URL,
                    json={
                        "name": "AT-失效渠道线索-%s" % uuid4().hex[:8],
                        "business_type": "education",
                        "channel_id": channel_id,
                    },
                )
            assert invalid_payload["data"]["cooperation_status"] == "invalid", invalid_payload
            forbidden_lead_payload = _parse_json(forbidden_lead_response, "使用失效渠道创建线索")
            assert forbidden_lead_payload.get("code") == CHANNEL_STATUS_NOT_ALLOWED_CODE, forbidden_lead_payload
            active_options_payload = _assert_success(channel_client.get(CHANNEL_OPTIONS_URL), "获取失效后的合作中渠道选项")
            assert all(item.get("id") != channel_id for item in active_options_payload["data"]), active_options_payload
        finally:
            _cleanup_temporary_lead(channel_client, lead_id)
            _cleanup_temporary_channel(channel_client, replacement_channel_id)
            _cleanup_temporary_channel(channel_client, channel_id)
