# -*- coding: utf-8 -*-
"""管理平台销售管理-线索管理接口自动化测试。

被测服务的接口前缀为 ``/v1``，统一响应格式为：
``{"code": 20000, "msg": "...", "data": ...}``。

测试环境、账号和写操作开关统一配置在
``config/project_information.py``。写操作会创建 ``AT-`` 前缀的临时渠道、
线索和客户，并在 ``finally`` 中清理；不依赖环境中已有业务数据。
"""
from datetime import date
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, MANAGEMENT_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
CHANNELS_URL = "/v1/channels"
CHANNEL_META_URL = "/v1/channels/meta"
LEADS_URL = "/v1/leads"
LEAD_STATS_URL = "/v1/leads/stats/overview"
FOLLOW_UP_MATERIALS_URL = "/v1/leads/follow-up-materials"
FOLLOW_UPS_URL = "/v1/follow-ups"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
PARAM_MISSING_CODE = 4101
FOLLOW_UP_VALIDATION_CODE = 40000
FORBIDDEN_CODE = 4030
UNAUTHORIZED_CODE = 4010
LEAD_NOT_FOUND_CODE = 5200
LEAD_STATUS_INVALID_CODE = 5201
LEAD_ALREADY_CONVERTED_CODE = 5202
BUSINESS_TYPE_INVALID_CODE = 5203
CHANNEL_NOT_FOUND_CODE = 5400
CHANNEL_STATUS_NOT_ALLOWED_CODE = 5401

BUSINESS_TYPES = {
    "government",
    "enterprise",
    "education",
    "medical",
    "finance",
    "military",
    "other",
}
LEAD_STATUSES = {"pending", "following", "converted", "invalid"}
STAT_STATUS_KEYS = {status.upper() for status in LEAD_STATUSES}
STAT_BUSINESS_TYPE_KEYS = {business_type.upper() for business_type in BUSINESS_TYPES}
LEAD_REQUIRED_FIELDS = {
    "id",
    "name",
    "business_type",
    "status",
    "creator",
    "channel_id",
    "channel_name",
    "attachments",
}


def _require_write_tests():
    """在全局写操作开关关闭时，明确跳过会产生业务数据的用例。"""
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _parse_json(response, action):
    """解析响应，失败时保留请求地址和响应片段便于排查。"""
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
    """校验管理平台的成功响应，并将账号权限不符标记为跳过。"""
    assert response.status_code == 200, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = _parse_json(response, action)
    if payload.get("code") == FORBIDDEN_CODE:
        pytest.skip("登录账号缺少线索管理或临时来源渠道所需权限")
    assert payload.get("code") == SUCCESS_CODE, "%s 业务失败：%s" % (action, payload)
    assert "data" in payload, "%s 成功响应缺少 data：%s" % (action, payload)
    return payload


def _assert_page_payload(payload, action, expected_page=None, expected_page_size=None):
    """校验列表、跟进记录和操作日志接口共用的分页响应。"""
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


def _assert_lead_shape(lead, action, expected_channel_id=None):
    """校验创建、详情和列表中的临时线索核心字段。"""
    assert isinstance(lead, dict), "%s 线索项应为对象，实际为 %r" % (action, lead)
    missing_fields = LEAD_REQUIRED_FIELDS - set(lead)
    assert not missing_fields, "%s 线索项缺少字段：%s；实际=%s" % (action, missing_fields, lead)
    assert isinstance(lead["id"], int) and lead["id"] > 0, "%s 线索 id 非法：%s" % (action, lead)
    assert isinstance(lead["name"], str) and lead["name"].strip(), "%s 线索名称为空：%s" % (action, lead)
    assert lead["business_type"] in BUSINESS_TYPES, "%s 业态类型不合法：%s" % (action, lead)
    assert lead["status"] in LEAD_STATUSES, "%s 状态不合法：%s" % (action, lead)
    assert isinstance(lead["creator"], str) and lead["creator"], "%s 创建人不合法：%s" % (action, lead)
    assert isinstance(lead["channel_id"], int) and lead["channel_id"] > 0, "%s 来源渠道 id 不合法：%s" % (action, lead)
    assert isinstance(lead["channel_name"], str) and lead["channel_name"], "%s 来源渠道名称为空：%s" % (action, lead)
    assert isinstance(lead["attachments"], list), "%s 附件字段应为数组：%s" % (action, lead)
    if expected_channel_id is not None:
        assert lead["channel_id"] == expected_channel_id, "%s 来源渠道不正确：%s" % (action, lead)


def _login_client(username, password, action):
    """登录内部账号，返回携带 Bearer Token 的客户端。"""
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
def lead_client():
    """登录线索管理账号；账号配置只来自 project_information.py。"""
    account = MANAGEMENT_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录管理平台")

    with allure.step("登录管理平台并获取线索管理 Token"):
        client = _login_client(username, password, "登录线索管理账号")
    yield client
    client.headers.pop("Authorization", None)


def _owner_id_for_create(client):
    """从渠道元数据选取负责人，供临时来源渠道创建使用。"""
    payload = _assert_success(client.get(CHANNEL_META_URL), "获取临时渠道创建元数据")
    owners = (payload.get("data") or {}).get("owners") or []
    if not owners:
        pytest.skip("当前环境没有可用负责人，无法创建线索来源渠道")
    owner_id = owners[0].get("id")
    assert isinstance(owner_id, int) and owner_id > 0, "渠道负责人不合法：%s" % owners[0]
    return owner_id


def _create_temporary_channel(client, owner_id, status="active"):
    """创建唯一的临时来源渠道，确保线索测试不污染已有业务数据。"""
    name = "AT-线索来源渠道-%s" % uuid4().hex[:12]
    body = {
        "name": name,
        "channel_type": "partner",
        "owner_id": owner_id,
        "cooperation_status": status,
        "start_date": date.today().isoformat(),
        "contact_person": "接口自动化来源联系人",
        "contact_phone": "13800000000",
        "channel_cost": "0.00",
        "remark": "线索管理自动化临时来源渠道，可安全删除",
    }
    payload = _assert_success(client.post(CHANNELS_URL, json=body), "创建临时线索来源渠道")
    channel = payload["data"]
    assert isinstance(channel, dict), "创建临时渠道返回格式错误：%s" % payload
    assert isinstance(channel.get("id"), int) and channel["id"] > 0, "临时渠道 id 非法：%s" % channel
    assert channel.get("name") == name, "临时渠道名称未正确保存：%s" % channel
    assert channel.get("cooperation_status") == status, "临时渠道状态未正确保存：%s" % channel
    return channel


def _create_temporary_lead(client, channel, **overrides):
    """使用合作中临时渠道创建唯一线索，并校验来源信息自动继承。"""
    body = {
        "name": "AT-线索管理-%s" % uuid4().hex[:12],
        "business_type": "education",
        "status": "pending",
        "channel_id": channel["id"],
        "remark": "线索管理接口自动化临时数据，可安全删除",
    }
    body.update(overrides)
    payload = _assert_success(client.post(LEADS_URL, json=body), "创建临时线索")
    lead = payload["data"]
    _assert_lead_shape(lead, "创建临时线索", expected_channel_id=channel["id"])
    assert lead["name"] == body["name"], "创建后的线索名称不正确：%s" % lead
    assert lead["channel_name"] == channel["name"], "线索未继承来源渠道名称：%s" % lead
    assert lead.get("channel_contact") == channel.get("contact_person"), "线索未继承来源渠道联系人：%s" % lead
    return lead


def _cleanup_temporary_lead(client, lead_id):
    """删除临时线索；转化过的线索同时清理关联客户。"""
    if not lead_id:
        return
    try:
        client.delete("%s/%s" % (LEADS_URL, lead_id), params={"delete_related_customer": "true"})
    except Exception:
        pass


def _cleanup_temporary_channel(client, channel_id):
    """删除尚无关联数据，或已完成线索清理的临时渠道。"""
    if not channel_id:
        return
    try:
        client.delete("%s/%s" % (CHANNELS_URL, channel_id))
    except Exception:
        pass


def _assert_error_code(response, action, expected_code, expected_http_status=200):
    """校验统一业务错误码。"""
    assert response.status_code == expected_http_status, "%s HTTP 状态异常：%s" % (action, response.text)
    payload = _parse_json(response, action)
    assert payload.get("code") == expected_code, "%s 错误码不正确：%s" % (action, payload)
    return payload


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-线索管理")
class Test线索管理查询与校验:
    """认证、列表、统计与不产生业务数据的参数校验。"""

    @allure.feature("访问权限")
    def test_未登录访问线索列表_返回未授权(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Authorization 请求线索列表"):
            response = anonymous_client.get(LEADS_URL)
        _assert_error_code(
            response,
            "未登录获取线索列表",
            UNAUTHORIZED_CODE,
            expected_http_status=401,
        )

    @allure.feature("查询与统计")
    def test_线索列表和统计概览返回完整结构(self, lead_client):
        with allure.step("查询默认线索列表"):
            list_payload = _assert_success(
                lead_client.get(LEADS_URL, params={"page": 1, "page_size": 5}),
                "获取线索列表",
            )
        list_data = _assert_page_payload(list_payload, "获取线索列表", expected_page=1, expected_page_size=5)
        status_counts = list_data.get("status_counts")
        assert isinstance(status_counts, dict), "线索列表缺少状态统计：%s" % list_data
        assert set(status_counts) == LEAD_STATUSES, "线索状态统计枚举不完整：%s" % status_counts
        assert all(isinstance(count, int) and count >= 0 for count in status_counts.values()), status_counts

        with allure.step("查询线索统计概览"):
            stats_payload = _assert_success(
                lead_client.get(LEAD_STATS_URL, params={"days": 30}),
                "获取线索统计概览",
            )
        stats = stats_payload["data"]
        assert isinstance(stats, dict), "线索统计 data 应为对象：%s" % stats_payload
        assert {"status_stats", "business_stats", "recent_leads", "total_leads", "total_follow_ups", "converted_count"} <= set(stats), stats
        assert set(stats["status_stats"]) == STAT_STATUS_KEYS, stats
        assert set(stats["business_stats"]) == STAT_BUSINESS_TYPE_KEYS, stats
        assert isinstance(stats["recent_leads"], list), stats
        assert all(isinstance(stats[key], int) and stats[key] >= 0 for key in ("total_leads", "total_follow_ups", "converted_count")), stats

    @allure.feature("创建校验")
    def test_新增线索_必填字段枚举和来源渠道校验(self, lead_client):
        invalid_requests = [
            ("缺少全部必填字段", {}, INVALID_PARAMS_CODE),
            (
                "缺少来源渠道",
                {"name": "AT-缺少来源渠道", "business_type": "education", "status": "pending"},
                PARAM_MISSING_CODE,
            ),
            (
                "业态类型非法",
                {"name": "AT-非法业态", "business_type": "invalid", "status": "pending"},
                BUSINESS_TYPE_INVALID_CODE,
            ),
            (
                "线索状态非法",
                {"name": "AT-非法状态", "business_type": "education", "status": "invalid-status"},
                LEAD_STATUS_INVALID_CODE,
            ),
            (
                "来源渠道不存在",
                {"name": "AT-不存在来源", "business_type": "education", "status": "pending", "channel_id": 2147483647},
                CHANNEL_NOT_FOUND_CODE,
            ),
        ]
        for action, body, expected_code in invalid_requests:
            with allure.step("创建线索：%s" % action):
                response = lead_client.post(LEADS_URL, json=body)
            _assert_error_code(response, "创建线索%s" % action, expected_code)

    @allure.feature("查询校验")
    def test_线索查询_非法分页和不存在详情返回业务错误码(self, lead_client):
        with allure.step("使用非法页码查询线索列表"):
            invalid_page_response = lead_client.get(LEADS_URL, params={"page": 0, "page_size": 10})
        _assert_error_code(invalid_page_response, "线索列表非法页码", INVALID_PARAMS_CODE)

        with allure.step("查询不存在的线索详情"):
            detail_response = lead_client.get("%s/%s" % (LEADS_URL, 2147483647))
        _assert_error_code(detail_response, "查询不存在的线索详情", LEAD_NOT_FOUND_CODE)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-线索管理")
class Test线索管理业务链路:
    """创建、筛选、编辑、跟进、状态、转客户和删除完整业务链路。"""

    @allure.feature("线索生命周期")
    def test_线索创建_筛选编辑详情与操作日志(self, lead_client):
        _require_write_tests()
        channel_id = None
        lead_id = None
        try:
            owner_id = _owner_id_for_create(lead_client)
            channel = _create_temporary_channel(lead_client, owner_id)
            channel_id = channel["id"]
            lead = _create_temporary_lead(lead_client, channel)
            lead_id = lead["id"]

            with allure.step("按名称、来源渠道、业态和待处理状态组合筛选线索"):
                list_payload = _assert_success(
                    lead_client.get(
                        LEADS_URL,
                        params={
                            "name": lead["name"],
                            "channel_id": channel_id,
                            "business_type": "education",
                            "status": "pending",
                            "page": 1,
                            "page_size": 10,
                        },
                    ),
                    "组合筛选线索",
                )
            list_data = _assert_page_payload(list_payload, "组合筛选线索", expected_page=1, expected_page_size=10)
            assert any(item.get("id") == lead_id for item in list_data["items"]), list_data

            updated_name = "AT-线索已编辑-%s" % uuid4().hex[:10]
            with allure.step("通过标准编辑接口更新名称、业态、备注和状态"):
                update_payload = _assert_success(
                    lead_client.put(
                        "%s/%s" % (LEADS_URL, lead_id),
                        json={
                            "name": updated_name,
                            "business_type": "enterprise",
                            "status": "following",
                            "remark": "标准编辑后的自动化备注",
                        },
                    ),
                    "标准编辑线索",
                )
            updated_lead = update_payload["data"]
            _assert_lead_shape(updated_lead, "标准编辑线索", expected_channel_id=channel_id)
            assert updated_lead["name"] == updated_name, updated_lead
            assert updated_lead["business_type"] == "enterprise", updated_lead
            assert updated_lead["status"] == "following", updated_lead
            assert updated_lead["remark"] == "标准编辑后的自动化备注", updated_lead

            simple_name = "AT-线索简化编辑-%s" % uuid4().hex[:10]
            with allure.step("通过简化编辑接口更新名称和备注"):
                simple_payload = _assert_success(
                    lead_client.put(
                        "%s/%s/simple" % (LEADS_URL, lead_id),
                        json={"name": simple_name, "remark": "简化编辑后的自动化备注"},
                    ),
                    "简化编辑线索",
                )
            assert simple_payload["data"]["name"] == simple_name, simple_payload
            assert simple_payload["data"]["remark"] == "简化编辑后的自动化备注", simple_payload
            assert simple_payload["data"]["channel_id"] == channel_id, "编辑不应清空来源渠道：%s" % simple_payload

            with allure.step("查询编辑后的线索详情与操作日志"):
                detail_payload = _assert_success(lead_client.get("%s/%s" % (LEADS_URL, lead_id)), "获取线索详情")
                logs_payload = _assert_success(
                    lead_client.get("%s/%s/logs" % (LEADS_URL, lead_id), params={"page": 1, "page_size": 20}),
                    "获取线索操作日志",
                )
            detail = detail_payload["data"]
            _assert_lead_shape(detail, "获取线索详情", expected_channel_id=channel_id)
            assert detail["name"] == simple_name and detail["status"] == "following", detail
            log_data = _assert_page_payload(logs_payload, "获取线索操作日志", expected_page=1, expected_page_size=20)
            operation_types = {item.get("operation_type") for item in log_data["items"]}
            assert {"create", "update"} <= operation_types, "线索创建和编辑日志不完整：%s" % log_data
        finally:
            _cleanup_temporary_lead(lead_client, lead_id)
            _cleanup_temporary_channel(lead_client, channel_id)

    @allure.feature("跟进管理")
    def test_线索跟进资料_创建查询作废删除与操作日志(self, lead_client):
        _require_write_tests()
        channel_id = None
        lead_id = None
        follow_up_id = None
        try:
            owner_id = _owner_id_for_create(lead_client)
            channel = _create_temporary_channel(lead_client, owner_id)
            channel_id = channel["id"]
            lead = _create_temporary_lead(lead_client, channel)
            lead_id = lead["id"]
            remark = "AT-跟进资料-%s" % uuid4().hex[:10]

            with allure.step("上传 JSON 格式线索跟进资料和附件元数据"):
                create_payload = _assert_success(
                    lead_client.post(
                        FOLLOW_UP_MATERIALS_URL,
                        json={
                            "data": {
                                "lead_id": lead_id,
                                "remark": remark,
                                "follow_up_type": "solution",
                                "attachments": [
                                    {
                                        "name": "AT-线索方案.txt",
                                        "url": "https://example.com/at-lead-plan.txt",
                                        "size": 12,
                                        "mime_type": "text/plain",
                                    }
                                ],
                            }
                        },
                    ),
                    "上传线索跟进资料",
                )
            follow_up = create_payload["data"]
            follow_up_id = follow_up.get("id")
            assert isinstance(follow_up_id, int) and follow_up_id > 0, "创建跟进资料未返回 id：%s" % follow_up
            assert follow_up.get("lead_id") == lead_id, follow_up
            assert follow_up.get("remark") == remark and follow_up.get("follow_up_type") == "solution", follow_up
            assert follow_up.get("status") == "normal", follow_up
            assert isinstance(follow_up.get("attachments"), list) and len(follow_up["attachments"]) == 1, follow_up

            with allure.step("查询线索跟进记录列表和详情"):
                list_payload = _assert_success(
                    lead_client.get("%s/%s/follow-ups" % (LEADS_URL, lead_id), params={"page": 1, "page_size": 10}),
                    "获取线索跟进记录列表",
                )
                detail_payload = _assert_success(
                    lead_client.get("%s/%s" % (FOLLOW_UPS_URL, follow_up_id)),
                    "获取跟进记录详情",
                )
            follow_up_list = _assert_page_payload(list_payload, "获取线索跟进记录列表", expected_page=1, expected_page_size=10)
            assert any(item.get("id") == follow_up_id for item in follow_up_list["items"]), follow_up_list
            assert detail_payload["data"].get("id") == follow_up_id, detail_payload

            with allure.step("作废跟进记录并校验作废原因"):
                invalid_payload = _assert_success(
                    lead_client.put(
                        "%s/%s/invalid" % (FOLLOW_UPS_URL, follow_up_id),
                        json={"invalid_reason": "接口自动化验证跟进作废"},
                    ),
                    "作废跟进记录",
                )
            assert invalid_payload["data"] is None, invalid_payload
            invalid_detail = _assert_success(
                lead_client.get("%s/%s" % (FOLLOW_UPS_URL, follow_up_id)),
                "获取已作废跟进记录详情",
            )["data"]
            assert invalid_detail.get("status") == "invalid", invalid_detail
            assert invalid_detail.get("invalid_reason") == "接口自动化验证跟进作废", invalid_detail

            with allure.step("删除已作废跟进记录"):
                delete_payload = _assert_success(
                    lead_client.delete("%s/%s" % (FOLLOW_UPS_URL, follow_up_id)),
                    "删除跟进记录",
                )
            assert delete_payload["data"] is None, delete_payload
            deleted_follow_up_id = follow_up_id
            follow_up_id = None
            after_delete_payload = _assert_success(
                lead_client.get("%s/%s/follow-ups" % (LEADS_URL, lead_id), params={"page": 1, "page_size": 10}),
                "删除后查询线索跟进记录",
            )
            after_delete = _assert_page_payload(after_delete_payload, "删除后查询线索跟进记录", expected_page=1, expected_page_size=10)
            assert all(item.get("id") != deleted_follow_up_id for item in after_delete["items"]), after_delete
        finally:
            if follow_up_id:
                try:
                    lead_client.delete("%s/%s" % (FOLLOW_UPS_URL, follow_up_id))
                except Exception:
                    pass
            _cleanup_temporary_lead(lead_client, lead_id)
            _cleanup_temporary_channel(lead_client, channel_id)

    @allure.feature("状态管理")
    def test_线索状态_跟进作废原因和状态筛选(self, lead_client):
        _require_write_tests()
        channel_id = None
        lead_id = None
        try:
            owner_id = _owner_id_for_create(lead_client)
            channel = _create_temporary_channel(lead_client, owner_id)
            channel_id = channel["id"]
            lead = _create_temporary_lead(lead_client, channel)
            lead_id = lead["id"]

            with allure.step("将待处理线索改为跟进中"):
                following_payload = _assert_success(
                    lead_client.put("%s/status" % LEADS_URL, json={"lead_id": lead_id, "status": "following"}),
                    "修改线索为跟进中",
                )
            assert following_payload["data"].get("status") == "following", following_payload

            with allure.step("作废线索但不提供作废原因应被拒绝"):
                missing_reason_response = lead_client.put(
                    "%s/status" % LEADS_URL,
                    json={"lead_id": lead_id, "status": "invalid"},
                )
            _assert_error_code(missing_reason_response, "作废线索缺少原因", FOLLOW_UP_VALIDATION_CODE)

            with allure.step("提供作废原因后将线索置为已作废"):
                invalid_payload = _assert_success(
                    lead_client.put(
                        "%s/status" % LEADS_URL,
                        json={
                            "lead_id": lead_id,
                            "status": "invalid",
                            "invalid_reason": "接口自动化验证线索作废原因",
                        },
                    ),
                    "作废线索",
                )
            invalid_lead = invalid_payload["data"]
            assert invalid_lead.get("status") == "invalid", invalid_lead
            assert invalid_lead.get("invalid_reason") == "接口自动化验证线索作废原因", invalid_lead

            with allure.step("按已作废状态筛选线索"):
                list_payload = _assert_success(
                    lead_client.get(
                        LEADS_URL,
                        params={"name": lead["name"], "status": "invalid", "page": 1, "page_size": 10},
                    ),
                    "按已作废状态筛选线索",
                )
            list_data = _assert_page_payload(list_payload, "按已作废状态筛选线索", expected_page=1, expected_page_size=10)
            assert any(item.get("id") == lead_id and item.get("invalid_reason") for item in list_data["items"]), list_data
        finally:
            _cleanup_temporary_lead(lead_client, lead_id)
            _cleanup_temporary_channel(lead_client, channel_id)

    @allure.feature("来源渠道约束")
    def test_非合作中渠道_不可作为线索来源(self, lead_client):
        _require_write_tests()
        channel_id = None
        try:
            owner_id = _owner_id_for_create(lead_client)
            channel = _create_temporary_channel(lead_client, owner_id, status="paused")
            channel_id = channel["id"]
            with allure.step("使用已暂停来源渠道创建线索"):
                response = lead_client.post(
                    LEADS_URL,
                    json={
                        "name": "AT-暂停来源线索-%s" % uuid4().hex[:10],
                        "business_type": "education",
                        "status": "pending",
                        "channel_id": channel_id,
                    },
                )
            _assert_error_code(response, "使用暂停渠道创建线索", CHANNEL_STATUS_NOT_ALLOWED_CODE)
        finally:
            _cleanup_temporary_channel(lead_client, channel_id)

    @allure.feature("线索转客户")
    def test_线索转客户_继承渠道已转化不可编辑并可联动删除(self, lead_client):
        _require_write_tests()
        channel_id = None
        lead_id = None
        customer_id = None
        try:
            owner_id = _owner_id_for_create(lead_client)
            channel = _create_temporary_channel(lead_client, owner_id)
            channel_id = channel["id"]
            lead = _create_temporary_lead(lead_client, channel)
            lead_id = lead["id"]

            with allure.step("将线索转化为客户"):
                convert_payload = _assert_success(
                    lead_client.post(
                        "%s/%s/convert-to-customer" % (LEADS_URL, lead_id),
                        json={
                            "name": "AT-线索转客户-%s" % uuid4().hex[:10],
                            "deployment_type": "saas",
                            "customer_type": "school",
                            "manager_name": "接口自动化客户联系人",
                            "manager_phone": "13900000000",
                            "service_period": 12,
                            "remarks": "线索管理自动化转化客户，可安全删除",
                        },
                    ),
                    "线索转客户",
                )
            converted_lead = (convert_payload["data"] or {}).get("lead") or {}
            customer = (convert_payload["data"] or {}).get("customer") or {}
            customer_id = customer.get("id")
            assert converted_lead.get("id") == lead_id and converted_lead.get("status") == "converted", convert_payload
            assert isinstance(customer_id, int) and customer_id > 0, "转化客户未返回 id：%s" % convert_payload
            assert customer.get("lead_id") == lead_id, "客户未关联来源线索：%s" % customer
            assert customer.get("channel_id") == channel_id, "客户未继承来源渠道 id：%s" % customer
            assert customer.get("channel_name") == channel["name"], "客户未继承来源渠道名称：%s" % customer

            with allure.step("已转化线索不允许再修改状态"):
                update_status_response = lead_client.put(
                    "%s/status" % LEADS_URL,
                    json={"lead_id": lead_id, "status": "following"},
                )
            _assert_error_code(update_status_response, "修改已转化线索状态", LEAD_ALREADY_CONVERTED_CODE)

            with allure.step("删除线索时同步删除关联客户"):
                delete_payload = _assert_success(
                    lead_client.delete(
                        "%s/%s" % (LEADS_URL, lead_id),
                        params={"delete_related_customer": "true"},
                    ),
                    "删除已转化线索及关联客户",
                )
            deleted_customer_ids = delete_payload["data"].get("deleted_related_customer_ids") or []
            assert customer_id in deleted_customer_ids, "删除结果未包含关联客户：%s" % delete_payload
            lead_id = None
            with allure.step("删除后查询线索详情应返回不存在"):
                detail_response = lead_client.get("%s/%s" % (LEADS_URL, converted_lead["id"]))
            _assert_error_code(detail_response, "查询已删除线索", LEAD_NOT_FOUND_CODE)
        finally:
            _cleanup_temporary_lead(lead_client, lead_id)
            _cleanup_temporary_channel(lead_client, channel_id)

    @allure.feature("删除管理")
    def test_未转化线索_可独立删除且详情不可见(self, lead_client):
        _require_write_tests()
        channel_id = None
        lead_id = None
        try:
            owner_id = _owner_id_for_create(lead_client)
            channel = _create_temporary_channel(lead_client, owner_id)
            channel_id = channel["id"]
            lead = _create_temporary_lead(lead_client, channel)
            lead_id = lead["id"]

            with allure.step("删除未转化线索"):
                delete_payload = _assert_success(
                    lead_client.delete("%s/%s" % (LEADS_URL, lead_id)),
                    "删除未转化线索",
                )
            assert delete_payload["data"].get("lead_id") == lead_id, delete_payload
            assert delete_payload["data"].get("deleted_related_customer_ids") == [], delete_payload
            deleted_lead_id = lead_id
            lead_id = None
            with allure.step("删除后查询线索详情"):
                detail_response = lead_client.get("%s/%s" % (LEADS_URL, deleted_lead_id))
            _assert_error_code(detail_response, "查询已删除未转化线索", LEAD_NOT_FOUND_CODE)
        finally:
            _cleanup_temporary_lead(lead_client, lead_id)
            _cleanup_temporary_channel(lead_client, channel_id)
