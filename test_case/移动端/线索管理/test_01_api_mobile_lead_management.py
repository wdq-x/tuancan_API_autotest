# -*- coding: utf-8 -*-
"""移动端线索管理接口自动化测试。

接口契约来源于 ``canteen_operate_platfrom_app`` Flutter 项目：

- ``login_request.dart``: ``POST /v1/login``，``client_type=mobile``。
- ``clue_request.dart``: 线索列表、详情、创建、编辑、删除和状态更新。
- ``channel_option_request.dart``: 移动端来源渠道选项。
- ``customer_request.dart``: 线索转客户。

写操作使用 ``AT-移动端线索-`` 前缀临时数据，并在 finally 中删除。创建线索时
优先使用移动端渠道选项接口返回的有效渠道，不创建或修改环境原有渠道。
"""
from datetime import date, timedelta
from uuid import uuid4

import allure
import pytest

from config.project_information import (
    ENABLE_WRITE_TESTS,
    MOBILE_TEST_ACCOUNT,
    default_headers,
)
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
LEADS_URL = "/v1/leads"
LEAD_STATUS_URL = "/v1/leads/status"
CHANNEL_OPTIONS_URL = "/v1/channels/options"
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
        pytest.skip("移动端测试账号缺少线索管理所需权限")
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


def _assert_lead_shape(lead, action, expected_channel_id=None):
    assert isinstance(lead, dict), "%s 线索项应为对象：%r" % (action, lead)
    missing_fields = LEAD_REQUIRED_FIELDS - set(lead)
    assert not missing_fields, "%s 线索项缺少字段 %s：%s" % (action, missing_fields, lead)
    assert isinstance(lead["id"], int) and lead["id"] > 0, "%s 线索 id 非法：%s" % (action, lead)
    assert isinstance(lead["name"], str) and lead["name"].strip(), "%s 线索名称为空：%s" % (action, lead)
    assert lead["business_type"] in BUSINESS_TYPES, "%s 业态类型非法：%s" % (action, lead)
    assert lead["status"] in LEAD_STATUSES, "%s 线索状态非法：%s" % (action, lead)
    assert isinstance(lead["channel_id"], int) and lead["channel_id"] > 0, "%s 来源渠道 id 非法：%s" % (action, lead)
    assert isinstance(lead["channel_name"], str) and lead["channel_name"], "%s 来源渠道名称为空：%s" % (action, lead)
    assert isinstance(lead["attachments"], list), "%s attachments 应为数组：%s" % (action, lead)
    if expected_channel_id is not None:
        assert lead["channel_id"] == expected_channel_id, "%s 来源渠道不正确：%s" % (action, lead)


def _login_mobile_client(username, password):
    client = HttpClient(headers=default_headers.copy())
    response = client.post(
        LOGIN_URL,
        json={
            "username": username,
            "password": password,
            "client_type": "mobile",
        },
    )
    payload = _assert_success(response, "移动端账号登录")
    token = (payload.get("data") or {}).get("access_token")
    assert token, "移动端登录成功但未返回 access_token：%s" % payload
    client.headers["Authorization"] = "Bearer %s" % token
    return client


@pytest.fixture(scope="module")
def mobile_lead_client():
    account = MOBILE_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MOBILE_TEST_ACCOUNT 或管理平台回退账号，无法登录移动端")

    with allure.step("使用 client_type=mobile 登录并获取 Token"):
        client = _login_mobile_client(username, password)
    yield client
    client.headers.pop("Authorization", None)


def _get_active_channel(client):
    payload = _assert_success(
        client.get(CHANNEL_OPTIONS_URL, params={"status": "active", "limit": 500}),
        "获取移动端来源渠道选项",
    )
    channels = payload["data"]
    assert isinstance(channels, list), "移动端渠道选项 data 应为数组：%s" % payload
    for channel in channels:
        if isinstance(channel, dict) and isinstance(channel.get("id"), int) and channel["id"] > 0:
            return channel
    pytest.skip("当前移动端账号没有可用于创建线索的合作中来源渠道")


def _create_temporary_lead(client, channel, **overrides):
    body = {
        "name": "AT-移动端线索-%s" % uuid4().hex[:12],
        "business_type": "education",
        "status": "pending",
        "remark": "移动端线索管理接口自动化临时数据，可安全删除",
        "channel_id": channel["id"],
    }
    body.update(overrides)
    payload = _assert_success(client.post(LEADS_URL, json=body), "移动端创建线索")
    lead = payload["data"]
    _assert_lead_shape(lead, "移动端创建线索", expected_channel_id=channel["id"])
    assert lead["name"] == body["name"], "创建线索名称不正确：%s" % lead
    return lead


def _cleanup_temporary_lead(client, lead_id):
    if not lead_id:
        return
    try:
        client.delete("%s/%s" % (LEADS_URL, lead_id), params={"delete_related_customer": "true"})
    except Exception:
        pass


def _cleanup_follow_up(client, follow_up_id):
    if not follow_up_id:
        return
    try:
        client.delete("%s/%s" % (FOLLOW_UPS_URL, follow_up_id))
    except Exception:
        pass


@allure.parent_suite("接口自动化")
@allure.suite("移动端-线索管理")
class Test移动端线索管理查询:
    """覆盖移动端列表页、渠道选择和详情页的只读请求。"""

    @allure.feature("移动端鉴权")
    def test_未登录访问移动端线索列表_返回未授权(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Token 请求移动端线索列表"):
            response = anonymous_client.get(LEADS_URL, params={"page": 1, "page_size": 10})
        _assert_error_code(
            response,
            "未登录获取移动端线索列表",
            UNAUTHORIZED_CODE,
            expected_http_status=401,
        )

    @allure.feature("列表与筛选")
    def test_移动端线索列表_分页状态业态与渠道选项(self, mobile_lead_client):
        with allure.step("获取移动端线索列表首页"):
            first_page = _assert_success(
                mobile_lead_client.get(LEADS_URL, params={"page": 1, "page_size": 10}),
                "移动端线索列表首页",
            )
        first_data = _assert_page_payload(first_page, "移动端线索列表首页", expected_page=1, expected_page_size=10)
        for item in first_data["items"]:
            _assert_lead_shape(item, "移动端线索列表项")

        with allure.step("按移动端跟进中 Tab 查询第二页"):
            following_page = _assert_success(
                mobile_lead_client.get(
                    LEADS_URL,
                    params={"status": "following", "page": 2, "page_size": 10},
                ),
                "移动端跟进中线索第二页",
            )
        _assert_page_payload(following_page, "移动端跟进中线索第二页", expected_page=2, expected_page_size=10)

        with allure.step("获取移动端新增和筛选使用的合作中渠道选项"):
            channels_payload = _assert_success(
                mobile_lead_client.get(CHANNEL_OPTIONS_URL, params={"status": "active", "limit": 500}),
                "移动端来源渠道选项",
            )
        assert isinstance(channels_payload["data"], list), "渠道选项返回格式不正确：%s" % channels_payload

    @allure.feature("参数与权限校验")
    def test_移动端线索_创建查询详情参数校验(self, mobile_lead_client):
        invalid_create_requests = [
            ("缺少全部必填字段", {}, INVALID_PARAMS_CODE),
            (
                "缺少来源渠道",
                {"name": "AT-移动端缺少渠道", "business_type": "education", "status": "pending"},
                PARAM_MISSING_CODE,
            ),
            (
                "非法业态",
                {"name": "AT-移动端非法业态", "business_type": "not-supported", "status": "pending"},
                BUSINESS_TYPE_INVALID_CODE,
            ),
            (
                "非法状态",
                {"name": "AT-移动端非法状态", "business_type": "education", "status": "not-supported"},
                LEAD_STATUS_INVALID_CODE,
            ),
            (
                "不存在的来源渠道",
                {
                    "name": "AT-移动端不存在渠道",
                    "business_type": "education",
                    "status": "pending",
                    "channel_id": 2147483647,
                },
                CHANNEL_NOT_FOUND_CODE,
            ),
        ]
        for action, body, expected_code in invalid_create_requests:
            with allure.step("移动端新增线索校验：%s" % action):
                response = mobile_lead_client.post(LEADS_URL, json=body)
            _assert_error_code(response, "移动端新增线索%s" % action, expected_code)

        with allure.step("移动端请求非法页码"):
            invalid_page_response = mobile_lead_client.get(LEADS_URL, params={"page": 0, "page_size": 10})
        _assert_error_code(invalid_page_response, "移动端线索列表非法页码", INVALID_PARAMS_CODE)

        with allure.step("移动端请求不存在的线索详情"):
            missing_detail_response = mobile_lead_client.get("%s/%s" % (LEADS_URL, 2147483647))
        _assert_error_code(missing_detail_response, "移动端不存在的线索详情", LEAD_NOT_FOUND_CODE)


@allure.parent_suite("接口自动化")
@allure.suite("移动端-线索管理")
class Test移动端线索管理业务链路:
    """覆盖 Flutter 移动端线索新增、编辑、详情、状态和删除流程。"""

    @allure.feature("线索生命周期")
    def test_移动端线索_创建筛选编辑详情状态与删除(self, mobile_lead_client):
        _require_write_tests()
        lead_id = None
        try:
            channel = _get_active_channel(mobile_lead_client)
            lead = _create_temporary_lead(mobile_lead_client, channel)
            lead_id = lead["id"]

            with allure.step("按移动端名称、业态、状态和来源渠道筛选新增线索"):
                list_payload = _assert_success(
                    mobile_lead_client.get(
                        LEADS_URL,
                        params={
                            "name": lead["name"],
                            "business_type": "education",
                            "status": "pending",
                            "channel_id": channel["id"],
                            "page": 1,
                            "page_size": 10,
                        },
                    ),
                    "移动端组合筛选线索",
                )
            list_data = _assert_page_payload(list_payload, "移动端组合筛选线索", 1, 10)
            assert any(item.get("id") == lead_id for item in list_data["items"]), list_data

            today = date.today()
            time_ranges = [
                ("今天", today, today),
                ("最近 7 天", today - timedelta(days=6), today),
                ("最近 30 天", today - timedelta(days=29), today),
                ("自定义时间", today, today),
            ]
            for range_name, start_date, end_date in time_ranges:
                with allure.step("按移动端%s时间范围筛选新增线索" % range_name):
                    range_payload = _assert_success(
                        mobile_lead_client.get(
                            LEADS_URL,
                            params={
                                "name": lead["name"],
                                "start_date": start_date.isoformat(),
                                "end_date": end_date.isoformat(),
                                "page": 1,
                                "page_size": 10,
                            },
                        ),
                        "移动端%s时间筛选" % range_name,
                    )
                range_data = _assert_page_payload(range_payload, "移动端%s时间筛选" % range_name, 1, 10)
                assert any(item.get("id") == lead_id for item in range_data["items"]), range_data

            updated_name = "AT-移动端线索已编辑-%s" % uuid4().hex[:10]
            with allure.step("按移动端编辑表单提交完整线索字段"):
                update_payload = _assert_success(
                    mobile_lead_client.put(
                        "%s/%s" % (LEADS_URL, lead_id),
                        json={
                            "name": updated_name,
                            "business_type": "enterprise",
                            "remark": "移动端编辑后的自动化备注",
                            "channel_id": channel["id"],
                            "status": "pending",
                        },
                    ),
                    "移动端编辑线索",
                )
            updated = update_payload["data"]
            _assert_lead_shape(updated, "移动端编辑线索", expected_channel_id=channel["id"])
            assert updated["name"] == updated_name, updated
            assert updated["business_type"] == "enterprise", updated

            with allure.step("打开移动端线索详情"):
                detail_payload = _assert_success(
                    mobile_lead_client.get("%s/%s" % (LEADS_URL, lead_id)),
                    "移动端线索详情",
                )
            detail = detail_payload["data"]
            _assert_lead_shape(detail, "移动端线索详情", expected_channel_id=channel["id"])
            assert detail["name"] == updated_name, detail

            with allure.step("查询移动端详情页展示的操作记录"):
                logs_payload = _assert_success(
                    mobile_lead_client.get(
                        "%s/%s/logs" % (LEADS_URL, lead_id),
                        params={"page": 1, "page_size": 20},
                    ),
                    "移动端线索操作记录",
                )
            logs_data = _assert_page_payload(logs_payload, "移动端线索操作记录", 1, 20)
            operation_types = {item.get("operation_type") for item in logs_data["items"]}
            assert {"create", "update"} <= operation_types, "移动端详情操作记录不完整：%s" % logs_data

            with allure.step("按移动端状态选择器将线索设为跟进中"):
                status_payload = _assert_success(
                    mobile_lead_client.put(
                        LEAD_STATUS_URL,
                        json={"lead_id": lead_id, "status": "following"},
                    ),
                    "移动端更新线索状态",
                )
            assert status_payload["data"].get("status") == "following", status_payload

            with allure.step("按跟进中 Tab 验证状态筛选"):
                following_payload = _assert_success(
                    mobile_lead_client.get(
                        LEADS_URL,
                        params={"name": updated_name, "status": "following", "page": 1, "page_size": 10},
                    ),
                    "移动端跟进中状态筛选",
                )
            following_data = _assert_page_payload(following_payload, "移动端跟进中状态筛选", 1, 10)
            assert any(item.get("id") == lead_id for item in following_data["items"]), following_data

            with allure.step("删除移动端临时线索"):
                delete_payload = _assert_success(
                    mobile_lead_client.delete("%s/%s" % (LEADS_URL, lead_id)),
                    "移动端删除线索",
                )
            assert delete_payload["data"].get("lead_id") == lead_id, delete_payload
            deleted_lead_id = lead_id
            lead_id = None

            with allure.step("删除后详情接口返回线索不存在"):
                deleted_response = mobile_lead_client.get("%s/%s" % (LEADS_URL, deleted_lead_id))
            _assert_error_code(deleted_response, "移动端删除后获取线索详情", LEAD_NOT_FOUND_CODE)
        finally:
            _cleanup_temporary_lead(mobile_lead_client, lead_id)

    @allure.feature("状态管理")
    def test_移动端线索_全部状态Tab与作废原因约束(self, mobile_lead_client):
        _require_write_tests()
        lead_id = None
        try:
            channel = _get_active_channel(mobile_lead_client)
            lead = _create_temporary_lead(mobile_lead_client, channel)
            lead_id = lead["id"]

            with allure.step("按移动端待处理 Tab 查询新建线索"):
                pending_payload = _assert_success(
                    mobile_lead_client.get(
                        LEADS_URL,
                        params={"name": lead["name"], "status": "pending", "page": 1, "page_size": 10},
                    ),
                    "移动端待处理Tab",
                )
            pending_data = _assert_page_payload(pending_payload, "移动端待处理Tab", 1, 10)
            assert any(item.get("id") == lead_id for item in pending_data["items"]), pending_data

            with allure.step("切换为跟进中并验证对应 Tab"):
                following_payload = _assert_success(
                    mobile_lead_client.put(LEAD_STATUS_URL, json={"lead_id": lead_id, "status": "following"}),
                    "移动端切换跟进中",
                )
            assert following_payload["data"].get("status") == "following", following_payload
            following_list_payload = _assert_success(
                mobile_lead_client.get(
                    LEADS_URL,
                    params={"name": lead["name"], "status": "following", "page": 1, "page_size": 10},
                ),
                "移动端跟进中Tab",
            )
            following_data = _assert_page_payload(following_list_payload, "移动端跟进中Tab", 1, 10)
            assert any(item.get("id") == lead_id for item in following_data["items"]), following_data

            with allure.step("移动端状态接口作废时不传原因应返回校验错误"):
                missing_reason_response = mobile_lead_client.put(
                    LEAD_STATUS_URL,
                    json={"lead_id": lead_id, "status": "invalid"},
                )
            _assert_error_code(
                missing_reason_response,
                "移动端作废线索缺少原因",
                FOLLOW_UP_VALIDATION_CODE,
            )

            with allure.step("按接口约束提交作废原因并验证已作废 Tab"):
                invalid_payload = _assert_success(
                    mobile_lead_client.put(
                        LEAD_STATUS_URL,
                        json={
                            "lead_id": lead_id,
                            "status": "invalid",
                            "invalid_reason": "移动端线索作废自动化原因",
                        },
                    ),
                    "移动端作废线索",
                )
            assert invalid_payload["data"].get("status") == "invalid", invalid_payload
            invalid_list_payload = _assert_success(
                mobile_lead_client.get(
                    LEADS_URL,
                    params={"name": lead["name"], "status": "invalid", "page": 1, "page_size": 10},
                ),
                "移动端已作废Tab",
            )
            invalid_data = _assert_page_payload(invalid_list_payload, "移动端已作废Tab", 1, 10)
            assert any(item.get("id") == lead_id for item in invalid_data["items"]), invalid_data
        finally:
            _cleanup_temporary_lead(mobile_lead_client, lead_id)

    @allure.feature("详情展示数据")
    def test_移动端线索详情_跟进记录附件与操作记录(self, mobile_lead_client):
        _require_write_tests()
        lead_id = None
        follow_up_id = None
        try:
            channel = _get_active_channel(mobile_lead_client)
            attachment = {
                "name": "AT-移动端线索附件.txt",
                "url": "https://example.com/at-mobile-lead-attachment.txt",
                "size": 12,
                "mime_type": "text/plain",
            }
            lead = _create_temporary_lead(mobile_lead_client, channel, attachments=[attachment])
            lead_id = lead["id"]
            follow_up_remark = "AT-移动端跟进记录-%s" % uuid4().hex[:10]

            with allure.step("创建移动端详情页展示的跟进记录和附件元数据"):
                follow_up_payload = _assert_success(
                    mobile_lead_client.post(
                        FOLLOW_UP_MATERIALS_URL,
                        json={
                            "data": {
                                "lead_id": lead_id,
                                "remark": follow_up_remark,
                                "follow_up_type": "solution",
                                "attachments": [attachment],
                            }
                        },
                    ),
                    "移动端创建线索跟进记录",
                )
            follow_up = follow_up_payload["data"]
            follow_up_id = follow_up.get("id")
            assert isinstance(follow_up_id, int) and follow_up_id > 0, follow_up_payload

            with allure.step("查询移动端详情模型所需的线索详情和跟进记录列表"):
                detail_payload = _assert_success(
                    mobile_lead_client.get("%s/%s" % (LEADS_URL, lead_id)),
                    "移动端详情展示数据",
                )
                follow_ups_payload = _assert_success(
                    mobile_lead_client.get(
                        "%s/%s/follow-ups" % (LEADS_URL, lead_id),
                        params={"page": 1, "page_size": 10},
                    ),
                    "移动端跟进记录列表",
                )
                logs_payload = _assert_success(
                    mobile_lead_client.get(
                        "%s/%s/logs" % (LEADS_URL, lead_id),
                        params={"page": 1, "page_size": 20},
                    ),
                    "移动端操作记录列表",
                )
            detail = detail_payload["data"]
            assert isinstance(detail.get("attachments"), list), "移动端详情 attachments 格式不正确：%s" % detail
            assert any(item.get("name") == attachment["name"] for item in detail["attachments"]), detail
            follow_ups_data = _assert_page_payload(follow_ups_payload, "移动端跟进记录列表", 1, 10)
            assert any(item.get("id") == follow_up_id for item in follow_ups_data["items"]), follow_ups_data
            logs_data = _assert_page_payload(logs_payload, "移动端操作记录列表", 1, 20)
            assert any(item.get("operation_type") == "create" for item in logs_data["items"]), logs_data

            with allure.step("删除移动端详情页跟进记录"):
                delete_follow_up_payload = _assert_success(
                    mobile_lead_client.delete("%s/%s" % (FOLLOW_UPS_URL, follow_up_id)),
                    "移动端删除跟进记录",
                )
            assert delete_follow_up_payload["data"] is None, delete_follow_up_payload
            follow_up_id = None
        finally:
            _cleanup_follow_up(mobile_lead_client, follow_up_id)
            _cleanup_temporary_lead(mobile_lead_client, lead_id)

    @allure.feature("线索转客户")
    def test_移动端线索_转客户后继承渠道并联动清理(self, mobile_lead_client):
        _require_write_tests()
        lead_id = None
        try:
            channel = _get_active_channel(mobile_lead_client)
            lead = _create_temporary_lead(mobile_lead_client, channel)
            lead_id = lead["id"]
            customer_name = "AT-移动端转客户-%s" % uuid4().hex[:10]
            today = date.today()
            valid_end = today + timedelta(days=365)

            with allure.step("按移动端客户转换表单提交客户信息"):
                convert_payload = _assert_success(
                    mobile_lead_client.post(
                        "%s/%s/convert-to-customer" % (LEADS_URL, lead_id),
                        json={
                            "name": customer_name,
                            "deployment_type": "saas",
                            "customer_type": "school",
                            "manager_name": "移动端自动化客户联系人",
                            "manager_phone": "13900000000",
                            "service_period": 12,
                            "valid_start": today.isoformat(),
                            "valid_end": valid_end.isoformat(),
                            "dining_limit": 100,
                            "pos_count": 1,
                            "remarks": "移动端线索转客户自动化临时数据，可安全删除",
                            "call_domain_api": False,
                            "attachments": [],
                            "lead_id": lead_id,
                        },
                    ),
                    "移动端线索转客户",
                )
            converted_lead = (convert_payload["data"] or {}).get("lead") or {}
            customer = (convert_payload["data"] or {}).get("customer") or {}
            customer_id = customer.get("id")
            assert converted_lead.get("id") == lead_id, convert_payload
            assert converted_lead.get("status") == "converted", convert_payload
            assert isinstance(customer_id, int) and customer_id > 0, "移动端转客户未返回客户 id：%s" % convert_payload
            assert customer.get("lead_id") == lead_id, "客户未关联来源线索：%s" % customer
            assert customer.get("channel_id") == channel["id"], "客户未继承来源渠道：%s" % customer

            with allure.step("按已转化客户筛选移动端线索"):
                converted_list_payload = _assert_success(
                    mobile_lead_client.get(
                        LEADS_URL,
                        params={
                            "converted_customer_id": customer_id,
                            "status": "converted",
                            "page": 1,
                            "page_size": 10,
                        },
                    ),
                    "移动端已转化Tab和关联客户筛选",
                )
            converted_data = _assert_page_payload(converted_list_payload, "移动端已转化Tab和关联客户筛选", 1, 10)
            assert any(item.get("id") == lead_id for item in converted_data["items"]), converted_data

            with allure.step("已转化线索不允许再通过移动端状态选择器修改"):
                update_status_response = mobile_lead_client.put(
                    LEAD_STATUS_URL,
                    json={"lead_id": lead_id, "status": "following"},
                )
            _assert_error_code(update_status_response, "移动端修改已转化线索状态", LEAD_ALREADY_CONVERTED_CODE)

            with allure.step("删除线索并同步清理转换出的客户"):
                delete_payload = _assert_success(
                    mobile_lead_client.delete(
                        "%s/%s" % (LEADS_URL, lead_id),
                        params={"delete_related_customer": "true"},
                    ),
                    "移动端删除已转化线索",
                )
            deleted_customer_ids = delete_payload["data"].get("deleted_related_customer_ids") or []
            assert customer_id in deleted_customer_ids, "删除结果未包含关联客户：%s" % delete_payload
            lead_id = None
        finally:
            _cleanup_temporary_lead(mobile_lead_client, lead_id)
