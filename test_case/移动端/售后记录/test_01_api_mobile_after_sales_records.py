# -*- coding: utf-8 -*-
"""移动端售后记录接口自动化测试。

接口契约来自 ``canteen_operate_platfrom_app`` 的售后记录模块：

- ``after_sales_record_request.dart``：项目/成员选择、我的记录、详情、新增和图片上传。
- ``after_sales_record_controller.dart``：移动端表单必填项、提交和我的记录列表。
- ``after_sales_record_detail_controller.dart``：详情与附件预览。

售后记录模块没有删除 API。写入用例会先创建 ``AT-移动端售后-`` 临时交付项目，
在项目下创建售后记录，并通过删除临时项目触发数据库 ``ON DELETE CASCADE`` 清理记录。
"""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, MOBILE_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
PROJECTS_URL = "/v1/project-delivery/projects"
AFTER_SALES_URL = "/v1/after-sales-records"
MOBILE_PROJECTS_URL = "%s/mobile/projects" % AFTER_SALES_URL
MY_RECORDS_URL = "%s/my" % AFTER_SALES_URL

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
PARAM_ERROR_CODE = 4100
FORBIDDEN_CODE = 4030
NOT_FOUND_CODE = 4040
TOKEN_INVALID_CODE = 5104

HANDLING_RESULTS = {"resolved", "follow_up", "unresolved"}
PROJECT_REQUIRED_FIELDS = {
    "id",
    "project_code",
    "project_name",
    "customer_name",
    "status",
    "version",
}
MOBILE_PROJECT_REQUIRED_FIELDS = {
    "project_id",
    "project_code",
    "project_name",
    "unit_name",
    "project_role",
    "project_manager_name",
}
PROJECT_MEMBER_REQUIRED_FIELDS = {"id", "project_id", "user_id", "user_name", "project_role", "is_active"}
RECORD_REQUIRED_FIELDS = {
    "id",
    "record_no",
    "project_id",
    "project_code",
    "project_name",
    "unit_name",
    "problem_description",
    "handling_method",
    "handling_result",
    "handling_result_label",
    "visit_time",
    "handler_ids",
    "handler_names",
    "photo_attachments",
    "photo_count",
    "has_signature",
    "customer_signature",
    "submitter_id",
    "submitter_name",
    "source_client",
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
        pytest.skip("测试账号缺少移动端售后记录或项目交付所需权限")
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
    assert isinstance(data.get("total"), int) and data["total"] >= 0, "%s total 非法：%s" % (action, data)
    assert data.get("page") == expected_page, "%s 页码回显不正确：%s" % (action, data)
    assert data.get("page_size") == expected_page_size, "%s 每页数量回显不正确：%s" % (action, data)
    assert len(data["items"]) <= expected_page_size, "%s 返回条数超过 page_size：%s" % (action, data)
    return data


def _assert_project_shape(project, action):
    assert isinstance(project, dict), "%s 项目应为对象：%r" % (action, project)
    missing = PROJECT_REQUIRED_FIELDS - set(project)
    assert not missing, "%s 项目缺少字段 %s：%s" % (action, missing, project)
    assert isinstance(project["id"], int) and project["id"] > 0, "%s 项目 id 非法：%s" % (action, project)
    assert isinstance(project["project_name"], str) and project["project_name"], "%s 项目名称为空：%s" % (action, project)
    assert isinstance(project["customer_name"], str) and project["customer_name"], "%s 客户名称为空：%s" % (action, project)


def _assert_mobile_project_shape(project, action):
    assert isinstance(project, dict), "%s 移动端可选项目应为对象：%r" % (action, project)
    missing = MOBILE_PROJECT_REQUIRED_FIELDS - set(project)
    assert not missing, "%s 移动端可选项目缺少字段 %s：%s" % (action, missing, project)
    assert isinstance(project["project_id"], int) and project["project_id"] > 0, "%s 项目 id 非法：%s" % (action, project)
    assert isinstance(project["project_name"], str) and project["project_name"], "%s 项目名称为空：%s" % (action, project)


def _assert_member_shape(member, action):
    assert isinstance(member, dict), "%s 项目成员应为对象：%r" % (action, member)
    missing = PROJECT_MEMBER_REQUIRED_FIELDS - set(member)
    assert not missing, "%s 项目成员缺少字段 %s：%s" % (action, missing, member)
    assert isinstance(member["id"], int) and member["id"] > 0, "%s 项目成员 id 非法：%s" % (action, member)
    assert isinstance(member["user_id"], int) and member["user_id"] > 0, "%s 成员 user_id 非法：%s" % (action, member)
    assert isinstance(member["is_active"], bool), "%s is_active 应为布尔值：%s" % (action, member)


def _assert_record_shape(record, action, expected_record_id=None):
    assert isinstance(record, dict), "%s 售后记录应为对象：%r" % (action, record)
    missing = RECORD_REQUIRED_FIELDS - set(record)
    assert not missing, "%s 售后记录缺少字段 %s：%s" % (action, missing, record)
    assert isinstance(record["id"], int) and record["id"] > 0, "%s 记录 id 非法：%s" % (action, record)
    assert isinstance(record["record_no"], str) and record["record_no"].startswith("AS-"), "%s 记录编号异常：%s" % (action, record)
    assert isinstance(record["project_id"], int) and record["project_id"] > 0, "%s 项目 id 非法：%s" % (action, record)
    assert record["handling_result"] in HANDLING_RESULTS, "%s 处理结果异常：%s" % (action, record)
    assert isinstance(record["handler_ids"], list), "%s handler_ids 应为数组：%s" % (action, record)
    assert isinstance(record["handler_names"], list), "%s handler_names 应为数组：%s" % (action, record)
    assert isinstance(record["photo_attachments"], list) and record["photo_attachments"], "%s 缺少现场照片：%s" % (action, record)
    assert record["photo_count"] == len(record["photo_attachments"]), "%s 照片数量不一致：%s" % (action, record)
    assert record["has_signature"] is True and isinstance(record["customer_signature"], dict), "%s 缺少客户签字：%s" % (action, record)
    assert record["source_client"] == "mobile", "%s 来源客户端不正确：%s" % (action, record)
    if expected_record_id is not None:
        assert record["id"] == expected_record_id, "%s 记录 id 不正确：%s" % (action, record)


def _login_mobile_client(username, password):
    client = HttpClient(headers=default_headers.copy())
    response = client.post(
        LOGIN_URL,
        json={"username": username, "password": password, "client_type": "mobile"},
    )
    payload = _assert_success(response, "移动端售后记录账号登录")
    token = (payload.get("data") or {}).get("access_token")
    assert token, "移动端登录成功但未返回 access_token：%s" % payload
    client.headers["Authorization"] = "Bearer %s" % token
    return client


@pytest.fixture(scope="module")
def mobile_after_sales_client():
    account = MOBILE_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录移动端售后记录")

    with allure.step("使用 client_type=mobile 登录并获取售后记录 Token"):
        client = _login_mobile_client(username, password)
    yield client
    client.headers.pop("Authorization", None)


def _create_temporary_project(client, scenario):
    name = "AT-移动端售后-%s-%s" % (scenario, uuid4().hex[:10])
    payload = _assert_success(
        client.post(
            PROJECTS_URL,
            json={
                "project_name": name,
                "customer_name": "AT-移动端售后客户-%s" % uuid4().hex[:8],
                "contract_no": "AT-MOBILE-AS-%s" % uuid4().hex[:8],
                "contract_summary": "移动端售后记录接口自动化临时项目",
                "is_external_purchase": True,
                "planned_start_date": date.today().isoformat(),
                "planned_end_date": (date.today() + timedelta(days=14)).isoformat(),
                "remark": "移动端售后记录自动化数据，可安全删除",
            },
        ),
        "创建移动端售后临时项目",
    )
    project = payload["data"]
    _assert_project_shape(project, "创建移动端售后临时项目")
    assert project["project_name"] == name, project
    return project


def _close_and_delete_project(client, project_id):
    close_payload = _assert_success(
        client.patch("%s/%s" % (PROJECTS_URL, project_id), json={"status": "closed"}),
        "关闭移动端售后临时项目",
    )
    assert close_payload["data"].get("status") == "closed", close_payload
    delete_payload = _assert_success(
        client.delete("%s/%s" % (PROJECTS_URL, project_id)),
        "删除移动端售后临时项目",
    )
    assert (delete_payload.get("data") or {}).get("id") == project_id, delete_payload


def _cleanup_project_quietly(client, project_id):
    if not project_id:
        return
    try:
        client.patch("%s/%s" % (PROJECTS_URL, project_id), json={"status": "closed"})
        client.delete("%s/%s" % (PROJECTS_URL, project_id))
    except Exception:
        pass


def _attachment(name, suffix):
    """按 DeliveryUploadedFile.toSubmitJson 的附件结构构造已上传文件元数据。"""
    url = "https://example.com/after-sales/%s-%s.jpg" % (suffix, uuid4().hex[:8])
    return {
        "attachment_id": url,
        "file_name": name,
        "file_size": 12,
        "mime_type": "image/jpeg",
        "download_url": url,
        "source_client": "mobile",
    }


def _record_body(project_id, handler_id, request_id=None, **overrides):
    body = {
        "project_id": project_id,
        "unit_name": "AT-移动端售后单位-%s" % uuid4().hex[:8],
        "problem_description": "移动端售后现场问题描述，用于接口自动化验证",
        "handling_method": "移动端售后现场处理方式，并完成复测验证",
        "handling_result": "resolved",
        "visit_time": datetime.now(timezone.utc).isoformat(),
        "handler_ids": [handler_id],
        "photo_attachments": [_attachment("AT-移动端售后现场照片.jpg", "photo")],
        "customer_signature": _attachment("AT-移动端客户签字.jpg", "signature"),
        "remark": "移动端售后记录接口自动化备注",
        "source_client": "mobile",
        "request_id": request_id or str(uuid4()),
    }
    body.update(overrides)
    return body


def _get_mobile_project_members(client, project_id):
    payload = _assert_success(
        client.get("%s/%s/members" % (MOBILE_PROJECTS_URL, project_id)),
        "获取移动端售后项目成员",
    )
    members = (payload["data"] or {}).get("items") or []
    assert isinstance(members, list) and members, "移动端售后项目成员为空：%s" % payload
    for member in members:
        _assert_member_shape(member, "移动端售后项目成员")
    return members


@allure.parent_suite("接口自动化")
@allure.suite("移动端-售后记录")
class Test移动端售后记录查询与异常:
    """覆盖移动端项目选择、我的记录和前端提交前可触发的服务端异常。"""

    @allure.feature("移动端鉴权")
    def test_未登录访问移动端我的售后记录_返回令牌无效(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Token 请求我的售后记录"):
            response = anonymous_client.get(MY_RECORDS_URL, params={"page": 1, "page_size": 20})
        _assert_error_code(response, "未登录获取移动端售后记录", TOKEN_INVALID_CODE)

    @allure.feature("参数与资源异常")
    def test_移动端售后项目和记录_非法分页不存在资源与必填参数校验(self, mobile_after_sales_client):
        with allure.step("移动端传入非法项目选择页码"):
            invalid_project_page = mobile_after_sales_client.get(
                MOBILE_PROJECTS_URL,
                params={"page": 0, "page_size": 20},
            )
        _assert_error_code(invalid_project_page, "移动端售后项目非法分页", INVALID_PARAMS_CODE)

        with allure.step("移动端传入非法我的记录页码"):
            invalid_record_page = mobile_after_sales_client.get(
                MY_RECORDS_URL,
                params={"page": 0, "page_size": 20},
            )
        _assert_error_code(invalid_record_page, "移动端我的售后记录非法分页", INVALID_PARAMS_CODE)

        with allure.step("移动端查询不存在项目成员"):
            missing_members = mobile_after_sales_client.get("%s/%s/members" % (MOBILE_PROJECTS_URL, 2147483647))
        _assert_error_code(missing_members, "移动端查询不存在售后项目成员", NOT_FOUND_CODE)

        with allure.step("移动端查询不存在售后记录详情"):
            missing_record = mobile_after_sales_client.get("%s/%s" % (AFTER_SALES_URL, 2147483647))
        _assert_error_code(missing_record, "移动端查询不存在售后记录", NOT_FOUND_CODE)

        invalid_bodies = [
            ("缺少全部必填字段", {}),
            (
                "处理结果非法",
                {
                    "project_id": 1,
                    "unit_name": "自动化单位",
                    "problem_description": "自动化问题",
                    "handling_method": "自动化处理",
                    "handling_result": "not-supported",
                    "visit_time": datetime.now(timezone.utc).isoformat(),
                    "photo_attachments": [_attachment("invalid.jpg", "invalid")],
                    "customer_signature": _attachment("signature.jpg", "invalid-signature"),
                },
            ),
            (
                "现场照片为空",
                {
                    "project_id": 1,
                    "unit_name": "自动化单位",
                    "problem_description": "自动化问题",
                    "handling_method": "自动化处理",
                    "handling_result": "resolved",
                    "visit_time": datetime.now(timezone.utc).isoformat(),
                    "photo_attachments": [],
                    "customer_signature": _attachment("signature.jpg", "empty-photo"),
                },
            ),
        ]
        for action, body in invalid_bodies:
            with allure.step("移动端提交售后记录校验：%s" % action):
                response = mobile_after_sales_client.post(AFTER_SALES_URL, json=body)
            _assert_error_code(response, "移动端提交售后记录%s" % action, INVALID_PARAMS_CODE)


@allure.parent_suite("接口自动化")
@allure.suite("移动端-售后记录")
class Test移动端售后记录业务链路:
    """覆盖移动端表单的项目选择、成员选择、提交、幂等和项目级清理。"""

    @allure.feature("项目选择与我的记录")
    def test_移动端售后记录_项目成员选择创建详情幂等与级联清理(self, mobile_after_sales_client):
        _require_write_tests()
        project_id = None
        record_id = None
        try:
            project = _create_temporary_project(mobile_after_sales_client, "完整链路")
            project_id = project["id"]

            with allure.step("按项目名称搜索移动端可选售后项目"):
                project_payload = _assert_success(
                    mobile_after_sales_client.get(
                        MOBILE_PROJECTS_URL,
                        params={"keyword": project["project_name"], "page": 1, "page_size": 20},
                    ),
                    "移动端搜索可选售后项目",
                )
            project_data = _assert_page_payload(project_payload, "移动端搜索可选售后项目", 1, 20)
            mobile_project = next((item for item in project_data["items"] if item.get("project_id") == project_id), None)
            assert mobile_project is not None, "移动端可选项目未包含临时项目：%s" % project_data
            _assert_mobile_project_shape(mobile_project, "移动端可选售后项目")

            with allure.step("选择项目后加载可选处理人员"):
                members = _get_mobile_project_members(mobile_after_sales_client, project_id)
            handler = next((item for item in members if item.get("is_active")), None)
            assert handler is not None, "临时项目没有可选的活动处理人员：%s" % members

            with allure.step("加载移动端我的售后记录首页和下一页"):
                first_page = _assert_success(
                    mobile_after_sales_client.get(MY_RECORDS_URL, params={"page": 1, "page_size": 10}),
                    "移动端我的售后记录首页",
                )
                second_page = _assert_success(
                    mobile_after_sales_client.get(MY_RECORDS_URL, params={"page": 2, "page_size": 10}),
                    "移动端我的售后记录下一页",
                )
            _assert_page_payload(first_page, "移动端我的售后记录首页", 1, 10)
            _assert_page_payload(second_page, "移动端我的售后记录下一页", 2, 10)

            request_id = str(uuid4())
            body = _record_body(project_id, handler["user_id"], request_id=request_id)
            with allure.step("提交移动端售后记录表单，包含现场照片和客户签字"):
                create_payload = _assert_success(
                    mobile_after_sales_client.post(AFTER_SALES_URL, json=body),
                    "移动端创建售后记录",
                )
            record = create_payload["data"]
            _assert_record_shape(record, "移动端创建售后记录")
            record_id = record["id"]
            assert record["project_id"] == project_id, record
            assert record["handler_ids"] == [handler["user_id"]], record
            assert record["unit_name"] == body["unit_name"], record
            assert record["handling_result"] == "resolved", record

            with allure.step("网络重试使用同一 request_id 提交，应返回同一售后记录"):
                repeated_payload = _assert_success(
                    mobile_after_sales_client.post(AFTER_SALES_URL, json=body),
                    "移动端售后记录幂等重试",
                )
            repeated = repeated_payload["data"]
            _assert_record_shape(repeated, "移动端售后记录幂等重试", expected_record_id=record_id)
            assert repeated["record_no"] == record["record_no"], repeated

            with allure.step("从移动端我的记录列表回查新建记录"):
                my_records_payload = _assert_success(
                    mobile_after_sales_client.get(MY_RECORDS_URL, params={"page": 1, "page_size": 100}),
                    "移动端回查我的售后记录",
                )
            my_records_data = _assert_page_payload(my_records_payload, "移动端回查我的售后记录", 1, 100)
            assert any(item.get("id") == record_id for item in my_records_data["items"]), my_records_data

            with allure.step("打开移动端售后记录详情并验证照片与签字预览地址"):
                detail_payload = _assert_success(
                    mobile_after_sales_client.get("%s/%s" % (AFTER_SALES_URL, record_id)),
                    "移动端售后记录详情",
                )
            detail = detail_payload["data"]
            _assert_record_shape(detail, "移动端售后记录详情", expected_record_id=record_id)
            assert detail["photo_attachments"][0].get("preview_url"), detail
            assert detail["customer_signature"].get("preview_url"), detail

            with allure.step("关闭并删除临时项目，售后记录应通过外键级联清理"):
                _close_and_delete_project(mobile_after_sales_client, project_id)
            deleted_project_id = project_id
            project_id = None

            with allure.step("级联删除后售后记录详情返回不存在"):
                missing_response = mobile_after_sales_client.get("%s/%s" % (AFTER_SALES_URL, record_id))
            _assert_error_code(missing_response, "移动端售后记录级联删除后查询", NOT_FOUND_CODE)
            assert deleted_project_id > 0
        finally:
            _cleanup_project_quietly(mobile_after_sales_client, project_id)

    @allure.feature("业务异常")
    def test_移动端售后记录_不存在项目和不可用处理人员被拒绝(self, mobile_after_sales_client):
        _require_write_tests()
        with allure.step("提交不存在项目的售后记录"):
            missing_project_response = mobile_after_sales_client.post(
                AFTER_SALES_URL,
                json=_record_body(2147483647, handler_id=1),
            )
        _assert_error_code(missing_project_response, "移动端提交不存在项目售后记录", PARAM_ERROR_CODE)

        project_id = None
        try:
            project = _create_temporary_project(mobile_after_sales_client, "异常")
            project_id = project["id"]
            with allure.step("提交不存在处理人员的售后记录"):
                missing_handler_response = mobile_after_sales_client.post(
                    AFTER_SALES_URL,
                    json=_record_body(project_id, handler_id=2147483647),
                )
            _assert_error_code(missing_handler_response, "移动端提交不存在处理人员售后记录", PARAM_ERROR_CODE)
        finally:
            _cleanup_project_quietly(mobile_after_sales_client, project_id)
