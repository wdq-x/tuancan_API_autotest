# -*- coding: utf-8 -*-
"""移动端点位勘察接口自动化测试。

接口契约来源于 ``canteen_operate_platfrom_app`` 的 ``site_survey`` 模块：

- ``site_survey_request.dart``：勘察单、学校、设备、点位、照片、校验和导出请求。
- ``site_survey_controller.dart``：创建、编辑草稿整体提交、照片标注和导出前校验。
- ``site_survey_models.dart``：移动端勘察单的层级数据和响应字段。

写操作均创建 ``AT-移动端点位勘察-`` 前缀数据，结束时调用移动端删除接口软删除勘察单。
"""
from uuid import uuid4

import allure
import pytest
import requests

from config.project_information import ENABLE_WRITE_TESTS, MOBILE_TEST_ACCOUNT, default_headers
from utils.http_client import NO_PROXIES, HttpClient


LOGIN_URL = "/v1/login"
SURVEYS_URL = "/v1/project-delivery/site-surveys"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
PARAM_ERROR_CODE = 4100
NAME_ALREADY_EXISTS_CODE = 5001
FORBIDDEN_CODE = 4030
NOT_FOUND_CODE = 4040
TOKEN_INVALID_CODE = 5104
VERSION_CONFLICT_CODE = 409110
EXPORT_BLOCKED_CODE = 409120

SURVEY_STATUSES = {"collecting", "completed", "exported"}
MARK_TYPES = {"none", "rect", "circle"}
SURVEY_REQUIRED_FIELDS = {
    "id",
    "survey_no",
    "project_name",
    "customer_name",
    "status",
    "status_label",
    "version",
    "school_count",
    "device_count",
    "position_count",
    "photo_count",
}
SCHOOL_REQUIRED_FIELDS = {"id", "school_name", "device_count", "position_count", "photo_count"}
DEVICE_REQUIRED_FIELDS = {
    "id",
    "school_id",
    "device_name",
    "quantity",
    "unit",
    "position_count",
    "position_quantity_total",
    "photo_count",
}
POSITION_REQUIRED_FIELDS = {"id", "school_id", "device_id", "position_name", "position_quantity", "photo_count"}


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
        pytest.skip("测试账号缺少移动端点位勘察所需权限")
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


def _assert_survey_shape(survey, action, expected_survey_id=None):
    assert isinstance(survey, dict), "%s 勘察单应为对象：%r" % (action, survey)
    missing = SURVEY_REQUIRED_FIELDS - set(survey)
    assert not missing, "%s 勘察单缺少字段 %s：%s" % (action, missing, survey)
    assert isinstance(survey["id"], int) and survey["id"] > 0, "%s 勘察单 id 非法：%s" % (action, survey)
    assert isinstance(survey["survey_no"], str) and survey["survey_no"].startswith("SS-"), "%s 勘察单编号异常：%s" % (action, survey)
    assert isinstance(survey["project_name"], str) and survey["project_name"], "%s 项目名称为空：%s" % (action, survey)
    assert isinstance(survey["customer_name"], str) and survey["customer_name"], "%s 客户名称为空：%s" % (action, survey)
    assert survey["status"] in SURVEY_STATUSES, "%s 勘察单状态非法：%s" % (action, survey)
    assert isinstance(survey["version"], int) and survey["version"] >= 1, "%s 勘察单版本号非法：%s" % (action, survey)
    if expected_survey_id is not None:
        assert survey["id"] == expected_survey_id, "%s 勘察单 id 不正确：%s" % (action, survey)


def _assert_school_shape(school, action):
    assert isinstance(school, dict), "%s 学校应为对象：%r" % (action, school)
    missing = SCHOOL_REQUIRED_FIELDS - set(school)
    assert not missing, "%s 学校缺少字段 %s：%s" % (action, missing, school)
    assert isinstance(school["id"], int) and school["id"] > 0, "%s 学校 id 非法：%s" % (action, school)
    assert isinstance(school["school_name"], str) and school["school_name"], "%s 学校名称为空：%s" % (action, school)


def _assert_device_shape(device, action):
    assert isinstance(device, dict), "%s 设备应为对象：%r" % (action, device)
    missing = DEVICE_REQUIRED_FIELDS - set(device)
    assert not missing, "%s 设备缺少字段 %s：%s" % (action, missing, device)
    assert isinstance(device["id"], int) and device["id"] > 0, "%s 设备 id 非法：%s" % (action, device)
    assert isinstance(device["quantity"], int) and device["quantity"] >= 0, "%s 设备数量非法：%s" % (action, device)


def _assert_position_shape(position, action):
    assert isinstance(position, dict), "%s 点位应为对象：%r" % (action, position)
    missing = POSITION_REQUIRED_FIELDS - set(position)
    assert not missing, "%s 点位缺少字段 %s：%s" % (action, missing, position)
    assert isinstance(position["id"], int) and position["id"] > 0, "%s 点位 id 非法：%s" % (action, position)
    assert isinstance(position["position_quantity"], int) and position["position_quantity"] >= 0, "%s 点位数量非法：%s" % (action, position)


def _login_mobile_client(username, password):
    client = HttpClient(headers=default_headers.copy())
    response = client.post(
        LOGIN_URL,
        json={"username": username, "password": password, "client_type": "mobile"},
    )
    payload = _assert_success(response, "移动端点位勘察账号登录")
    token = (payload.get("data") or {}).get("access_token")
    assert token, "移动端登录成功但未返回 access_token：%s" % payload
    client.headers["Authorization"] = "Bearer %s" % token
    return client


@pytest.fixture(scope="module")
def mobile_site_survey_client():
    account = MOBILE_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录移动端点位勘察")

    with allure.step("使用 client_type=mobile 登录并获取点位勘察 Token"):
        client = _login_mobile_client(username, password)
    yield client
    client.headers.pop("Authorization", None)


def _create_survey_body(name=None, request_id=None, **overrides):
    body = {
        "project_name": name or "AT-移动端点位勘察-%s" % uuid4().hex[:10],
        "customer_name": "AT-移动端勘察客户-%s" % uuid4().hex[:8],
        "remark": "移动端点位勘察接口自动化临时数据",
        "source_client": "mobile",
        "request_id": request_id or str(uuid4()),
    }
    body.update(overrides)
    return body


def _create_temporary_survey(client, scenario):
    body = _create_survey_body(name="AT-移动端点位勘察-%s-%s" % (scenario, uuid4().hex[:8]))
    payload = _assert_success(client.post(SURVEYS_URL, json=body), "创建移动端点位勘察单")
    survey = payload["data"]
    _assert_survey_shape(survey, "创建移动端点位勘察单")
    assert survey["project_name"] == body["project_name"], survey
    return survey, body


def _cleanup_survey_quietly(client, survey_id):
    if not survey_id:
        return
    try:
        client.delete("%s/%s" % (SURVEYS_URL, survey_id))
    except Exception:
        pass


def _file_payload(name, suffix):
    """模拟移动端 uploadImageBytes 成功后的 DeliveryUploadedFile.toSubmitJson 结构。"""
    url = "https://example.com/site-surveys/%s-%s.jpg" % (suffix, uuid4().hex[:8])
    return {
        "attachment_id": url,
        "file_name": name,
        "file_size": 12,
        "mime_type": "image/jpeg",
        "download_url": url,
    }


def _create_complete_hierarchy(client, survey_id):
    school_payload = _assert_success(
        client.post(
            "%s/%s/schools" % (SURVEYS_URL, survey_id),
            json={"school_name": "AT-移动端勘察学校-%s" % uuid4().hex[:8], "remark": "自动化学校"},
        ),
        "移动端新增勘察学校",
    )
    school = school_payload["data"]
    _assert_school_shape(school, "移动端新增勘察学校")

    device_payload = _assert_success(
        client.post(
            "%s/%s/schools/%s/devices" % (SURVEYS_URL, survey_id, school["id"]),
            json={
                "device_name": "摄像头",
                "quantity": 2,
                "unit": "台",
                "network": "校园内网",
                "remark": "移动端自动化设备",
            },
        ),
        "移动端新增勘察设备",
    )
    device = device_payload["data"]
    _assert_device_shape(device, "移动端新增勘察设备")

    position_payload = _assert_success(
        client.post(
            "%s/%s/devices/%s/positions" % (SURVEYS_URL, survey_id, device["id"]),
            json={
                "position_name": "食堂入口点位",
                "position_quantity": 2,
                "install_description": "入口右侧立柱安装，覆盖进出通道",
            },
        ),
        "移动端新增勘察点位",
    )
    position = position_payload["data"]
    _assert_position_shape(position, "移动端新增勘察点位")
    return school, device, position


def _assert_docx_response(response, action, expected_disposition):
    assert response.status_code == 200, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    content_type = response.headers.get("Content-Type", "")
    disposition = response.headers.get("Content-Disposition", "")
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in content_type, (
        "%s Content-Type 不正确：%s" % (action, content_type)
    )
    assert expected_disposition in disposition, "%s Content-Disposition 不正确：%s" % (action, disposition)
    assert response.content[:2] == b"PK", "%s 返回内容不是 docx 文件：%s" % (action, response.content[:100])


def _get_binary(client, path, params=None):
    return requests.get(
        client._url(path),
        params=params,
        headers=client.headers,
        timeout=client.timeout,
        proxies=NO_PROXIES,
    )


@allure.parent_suite("接口自动化")
@allure.suite("移动端-点位勘察")
class Test移动端点位勘察查询与异常:
    """覆盖鉴权、列表、创建参数与层级资源异常。"""

    @allure.feature("移动端鉴权")
    def test_未登录访问移动端点位勘察列表_返回令牌无效(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Token 请求点位勘察列表"):
            response = anonymous_client.get(SURVEYS_URL, params={"page": 1, "page_size": 20})
        _assert_error_code(response, "未登录获取移动端点位勘察列表", TOKEN_INVALID_CODE)

    @allure.feature("参数与资源异常")
    def test_移动端点位勘察_非法分页创建参数和不存在资源(self, mobile_site_survey_client):
        with allure.step("移动端请求非法勘察列表页码"):
            invalid_page = mobile_site_survey_client.get(SURVEYS_URL, params={"page": 0, "page_size": 20})
        _assert_error_code(invalid_page, "移动端点位勘察非法分页", INVALID_PARAMS_CODE)

        invalid_bodies = [
            ("缺少全部必填字段", {}),
            ("项目名称为空", _create_survey_body(project_name="", request_id=str(uuid4()))),
            ("客户名称为空", _create_survey_body(customer_name="", request_id=str(uuid4()))),
        ]
        for action, body in invalid_bodies:
            with allure.step("移动端创建点位勘察校验：%s" % action):
                response = mobile_site_survey_client.post(SURVEYS_URL, json=body)
            _assert_error_code(response, "移动端创建点位勘察%s" % action, INVALID_PARAMS_CODE)

        with allure.step("移动端查询不存在勘察单"):
            missing_survey = mobile_site_survey_client.get("%s/%s" % (SURVEYS_URL, 2147483647))
        _assert_error_code(missing_survey, "移动端查询不存在勘察单", NOT_FOUND_CODE)

        with allure.step("移动端向不存在勘察单创建学校"):
            missing_school_parent = mobile_site_survey_client.post(
                "%s/%s/schools" % (SURVEYS_URL, 2147483647),
                json={"school_name": "不存在勘察单的学校"},
            )
        _assert_error_code(missing_school_parent, "移动端向不存在勘察单创建学校", NOT_FOUND_CODE)


@allure.parent_suite("接口自动化")
@allure.suite("移动端-点位勘察")
class Test移动端点位勘察业务链路:
    """覆盖勘察单、层级录入、照片标注、草稿整体提交和导出校验。"""

    @allure.feature("勘察单生命周期")
    def test_移动端点位勘察_创建幂等搜索更新删除完整链路(self, mobile_site_survey_client):
        _require_write_tests()
        survey_id = None
        try:
            request_id = str(uuid4())
            body = _create_survey_body(request_id=request_id)
            with allure.step("移动端创建点位勘察单"):
                create_payload = _assert_success(
                    mobile_site_survey_client.post(SURVEYS_URL, json=body),
                    "移动端创建点位勘察单",
                )
            survey = create_payload["data"]
            _assert_survey_shape(survey, "移动端创建点位勘察单")
            survey_id = survey["id"]

            with allure.step("网络重试使用相同 request_id，应返回同一勘察单"):
                duplicate_payload = _assert_success(
                    mobile_site_survey_client.post(SURVEYS_URL, json=body),
                    "移动端点位勘察幂等重试",
                )
            _assert_survey_shape(duplicate_payload["data"], "移动端点位勘察幂等重试", expected_survey_id=survey_id)

            with allure.step("按项目名称搜索并打开勘察单详情"):
                list_payload = _assert_success(
                    mobile_site_survey_client.get(
                        SURVEYS_URL,
                        params={"keyword": body["project_name"], "status": "collecting", "page": 1, "page_size": 20},
                    ),
                    "移动端搜索点位勘察单",
                )
            list_data = _assert_page_payload(list_payload, "移动端搜索点位勘察单", 1, 20)
            assert any(item.get("id") == survey_id for item in list_data["items"]), list_data
            detail_payload = _assert_success(
                mobile_site_survey_client.get("%s/%s" % (SURVEYS_URL, survey_id)),
                "移动端点位勘察详情",
            )
            _assert_survey_shape(detail_payload["data"], "移动端点位勘察详情", expected_survey_id=survey_id)

            with allure.step("按当前版本更新移动端勘察备注"):
                update_payload = _assert_success(
                    mobile_site_survey_client.patch(
                        "%s/%s" % (SURVEYS_URL, survey_id),
                        json={"remark": "移动端更新后的勘察备注", "version": survey["version"]},
                    ),
                    "移动端更新点位勘察单",
                )
            updated = update_payload["data"]
            _assert_survey_shape(updated, "移动端更新点位勘察单", expected_survey_id=survey_id)
            assert updated.get("remark") == "移动端更新后的勘察备注", updated

            with allure.step("删除移动端临时勘察单"):
                delete_payload = _assert_success(
                    mobile_site_survey_client.delete("%s/%s" % (SURVEYS_URL, survey_id)),
                    "移动端删除点位勘察单",
                )
            assert delete_payload["data"].get("id") == survey_id, delete_payload
            deleted_survey_id = survey_id
            survey_id = None

            with allure.step("删除后勘察单详情返回不存在"):
                missing_response = mobile_site_survey_client.get("%s/%s" % (SURVEYS_URL, deleted_survey_id))
            _assert_error_code(missing_response, "移动端删除后查询点位勘察单", NOT_FOUND_CODE)
        finally:
            _cleanup_survey_quietly(mobile_site_survey_client, survey_id)

    @allure.feature("学校设备点位照片")
    def test_移动端点位勘察_学校设备点位照片标注校验与删除(self, mobile_site_survey_client):
        _require_write_tests()
        survey_id = None
        try:
            survey, _ = _create_temporary_survey(mobile_site_survey_client, "层级链路")
            survey_id = survey["id"]
            with allure.step("新增学校、设备和点位"):
                school, device, position = _create_complete_hierarchy(mobile_site_survey_client, survey_id)

            with allure.step("同一勘察单创建重名学校应被拒绝"):
                duplicate_school_response = mobile_site_survey_client.post(
                    "%s/%s/schools" % (SURVEYS_URL, survey_id),
                    json={"school_name": school["school_name"]},
                )
            _assert_error_code(duplicate_school_response, "移动端创建重名勘察学校", NAME_ALREADY_EXISTS_CODE)

            with allure.step("设备数量为负数应被参数校验拒绝"):
                invalid_device_response = mobile_site_survey_client.post(
                    "%s/%s/schools/%s/devices" % (SURVEYS_URL, survey_id, school["id"]),
                    json={"device_name": "非法设备", "quantity": -1, "unit": "台"},
                )
            _assert_error_code(invalid_device_response, "移动端创建非法数量设备", INVALID_PARAMS_CODE)

            with allure.step("点位照片使用非法标记类型应被拒绝"):
                invalid_photo_response = mobile_site_survey_client.post(
                    "%s/%s/positions/%s/photos" % (SURVEYS_URL, survey_id, position["id"]),
                    json={"original_file": _file_payload("invalid.jpg", "invalid"), "mark_type": "line"},
                )
            _assert_error_code(invalid_photo_response, "移动端创建非法标记照片", INVALID_PARAMS_CODE)

            original_file = _file_payload("AT-移动端勘察原图.jpg", "original")
            marked_file = _file_payload("AT-移动端勘察标记图.jpg", "marked")
            with allure.step("上传后的照片元数据保存为圆形标注照片"):
                photo_payload = _assert_success(
                    mobile_site_survey_client.post(
                        "%s/%s/positions/%s/photos" % (SURVEYS_URL, survey_id, position["id"]),
                        json={
                            "original_file": original_file,
                            "marked_file": marked_file,
                            "mark_type": "circle",
                            "mark_data": {"x": 0.5, "y": 0.4, "radius": 0.2},
                        },
                    ),
                    "移动端保存点位标注照片",
                )
            photo = photo_payload["data"]
            assert isinstance(photo.get("id"), int) and photo["id"] > 0, photo
            assert photo.get("mark_type") == "circle", photo
            assert photo.get("display_file"), photo

            with allure.step("修改照片标注为矩形"):
                mark_payload = _assert_success(
                    mobile_site_survey_client.patch(
                        "%s/%s/photos/%s/mark" % (SURVEYS_URL, survey_id, photo["id"]),
                        json={
                            "marked_file": marked_file,
                            "mark_type": "rect",
                            "mark_data": {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.3},
                        },
                    ),
                    "移动端更新照片标注",
                )
            assert mark_payload["data"].get("mark_type") == "rect", mark_payload

            with allure.step("查询勘察校验结果，完整层级应允许导出"):
                validation_payload = _assert_success(
                    mobile_site_survey_client.post("%s/%s/validate" % (SURVEYS_URL, survey_id)),
                    "移动端校验点位勘察单",
                )
            validation = validation_payload["data"]
            assert validation.get("blockers") == [], validation
            assert validation.get("can_export") is True, validation

            with allure.step("删除设备后应级联删除其点位和照片"):
                delete_device_payload = _assert_success(
                    mobile_site_survey_client.delete("%s/%s/devices/%s" % (SURVEYS_URL, survey_id, device["id"])),
                    "移动端删除勘察设备",
                )
            assert delete_device_payload["data"].get("id") == device["id"], delete_device_payload
            missing_position_response = mobile_site_survey_client.patch(
                "%s/%s/positions/%s" % (SURVEYS_URL, survey_id, position["id"]),
                json={"position_name": "不应更新"},
            )
            _assert_error_code(missing_position_response, "移动端删除设备后更新点位", NOT_FOUND_CODE)
        finally:
            _cleanup_survey_quietly(mobile_site_survey_client, survey_id)

    @allure.feature("编辑草稿")
    def test_移动端点位勘察_草稿整体提交版本冲突和重名异常(self, mobile_site_survey_client):
        _require_write_tests()
        survey_id = None
        try:
            survey, _ = _create_temporary_survey(mobile_site_survey_client, "草稿")
            survey_id = survey["id"]
            file_payload = _file_payload("AT-移动端草稿照片.jpg", "draft")
            valid_draft = {
                "project_name": "AT-移动端草稿项目-%s" % uuid4().hex[:8],
                "customer_name": "AT-移动端草稿客户-%s" % uuid4().hex[:8],
                "remark": "移动端草稿整体提交",
                "version": survey["version"],
                "schools": [
                    {
                        "school_name": "AT-移动端草稿学校",
                        "devices": [
                            {
                                "device_name": "门禁设备",
                                "quantity": 1,
                                "unit": "台",
                                "network": "办公网",
                                "photos": [
                                    {
                                        "original_file": file_payload,
                                        "mark_type": "none",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            with allure.step("按移动端编辑草稿一次性提交学校设备和照片"):
                commit_payload = _assert_success(
                    mobile_site_survey_client.put("%s/%s/draft-commit" % (SURVEYS_URL, survey_id), json=valid_draft),
                    "移动端提交点位勘察编辑草稿",
                )
            committed = commit_payload["data"]
            _assert_survey_shape(committed, "移动端提交点位勘察编辑草稿", expected_survey_id=survey_id)
            assert committed.get("school_count") == 1, committed
            assert committed.get("device_count") == 1, committed
            assert committed.get("position_count") == 1, committed
            assert committed.get("photo_count") == 1, committed

            with allure.step("使用过期版本再次提交草稿应返回版本冲突"):
                stale_draft = dict(valid_draft)
                stale_draft["version"] = survey["version"]
                stale_response = mobile_site_survey_client.put(
                    "%s/%s/draft-commit" % (SURVEYS_URL, survey_id),
                    json=stale_draft,
                )
            _assert_error_code(stale_response, "移动端提交过期版本勘察草稿", VERSION_CONFLICT_CODE)

            latest_payload = _assert_success(
                mobile_site_survey_client.get("%s/%s" % (SURVEYS_URL, survey_id)),
                "获取草稿提交后的勘察详情",
            )
            latest = latest_payload["data"]
            duplicate_draft = dict(valid_draft)
            duplicate_draft["version"] = latest["version"]
            duplicate_draft["schools"] = [
                {"school_name": "同名学校", "devices": []},
                {"school_name": "同名学校", "devices": []},
            ]
            with allure.step("草稿中出现重名学校应被拒绝"):
                duplicate_response = mobile_site_survey_client.put(
                    "%s/%s/draft-commit" % (SURVEYS_URL, survey_id),
                    json=duplicate_draft,
                )
            _assert_error_code(duplicate_response, "移动端提交重名学校勘察草稿", NAME_ALREADY_EXISTS_CODE)
        finally:
            _cleanup_survey_quietly(mobile_site_survey_client, survey_id)

    @allure.feature("层级编辑与操作日志")
    def test_移动端点位勘察_汇总层级编辑删除和日志回查(self, mobile_site_survey_client):
        _require_write_tests()
        survey_id = None
        try:
            survey, body = _create_temporary_survey(mobile_site_survey_client, "层级编辑")
            survey_id = survey["id"]
            school, device, position = _create_complete_hierarchy(mobile_site_survey_client, survey_id)

            with allure.step("按项目关键字读取点位勘察汇总数据"):
                summary_payload = _assert_success(
                    mobile_site_survey_client.get(
                        "%s/summary" % SURVEYS_URL,
                        params={"keyword": body["project_name"]},
                    ),
                    "获取移动端点位勘察汇总",
                )
            summary = summary_payload["data"]
            expected_summary_keys = {
                "survey_count",
                "school_count",
                "device_count",
                "position_count",
                "photo_count",
                "export_count",
                "warning_count",
                "status_counts",
            }
            assert expected_summary_keys <= set(summary), summary
            assert summary["survey_count"] >= 1, summary
            assert summary["school_count"] >= 1, summary
            assert summary["device_count"] >= 1, summary
            assert summary["position_count"] >= 1, summary
            assert isinstance(summary["status_counts"], dict), summary

            with allure.step("更新学校、设备和点位的现场信息"):
                school_name = "AT-移动端更新学校-%s" % uuid4().hex[:8]
                school_payload = _assert_success(
                    mobile_site_survey_client.patch(
                        "%s/%s/schools/%s" % (SURVEYS_URL, survey_id, school["id"]),
                        json={"school_name": school_name, "remark": "AT-移动端更新学校备注", "sort_order": 9},
                    ),
                    "移动端更新勘察学校",
                )
                updated_school = school_payload["data"]
                _assert_school_shape(updated_school, "移动端更新勘察学校")
                assert updated_school.get("school_name") == school_name, updated_school
                assert updated_school.get("remark") == "AT-移动端更新学校备注", updated_school

                device_payload = _assert_success(
                    mobile_site_survey_client.patch(
                        "%s/%s/devices/%s" % (SURVEYS_URL, survey_id, device["id"]),
                        json={
                            "device_name": "AT-移动端更新摄像头",
                            "quantity": 3,
                            "unit": "台",
                            "network": "AT-移动端更新网络",
                            "remark": "AT-移动端更新设备备注",
                            "sort_order": 8,
                        },
                    ),
                    "移动端更新勘察设备",
                )
                updated_device = device_payload["data"]
                _assert_device_shape(updated_device, "移动端更新勘察设备")
                assert updated_device.get("device_name") == "AT-移动端更新摄像头", updated_device
                assert updated_device.get("quantity") == 3, updated_device
                assert updated_device.get("network") == "AT-移动端更新网络", updated_device

                position_payload = _assert_success(
                    mobile_site_survey_client.patch(
                        "%s/%s/positions/%s" % (SURVEYS_URL, survey_id, position["id"]),
                        json={
                            "position_name": "AT-移动端更新点位",
                            "position_quantity": 3,
                            "install_description": "AT-移动端更新安装说明",
                            "sort_order": 7,
                        },
                    ),
                    "移动端更新勘察点位",
                )
            updated_position = position_payload["data"]
            _assert_position_shape(updated_position, "移动端更新勘察点位")
            assert updated_position.get("position_name") == "AT-移动端更新点位", updated_position
            assert updated_position.get("position_quantity") == 3, updated_position
            assert updated_position.get("install_description") == "AT-移动端更新安装说明", updated_position

            with allure.step("删除学校前回查完整详情以及创建、更新日志"):
                detail_payload = _assert_success(
                    mobile_site_survey_client.get("%s/%s" % (SURVEYS_URL, survey_id)),
                    "回查移动端点位勘察编辑详情",
                )
            detail = detail_payload["data"]
            _assert_survey_shape(detail, "移动端点位勘察编辑详情", expected_survey_id=survey_id)
            updated_detail_school = next((item for item in detail.get("schools") or [] if item.get("id") == school["id"]), None)
            assert updated_detail_school is not None, detail
            nested_device = next((item for item in updated_detail_school.get("devices") or [] if item.get("id") == device["id"]), None)
            assert nested_device is not None, updated_detail_school
            nested_position = next((item for item in nested_device.get("positions") or [] if item.get("id") == position["id"]), None)
            assert nested_position is not None, nested_device
            assert nested_position.get("position_name") == "AT-移动端更新点位", nested_position

            logs_payload = _assert_success(
                mobile_site_survey_client.get(
                    "%s/%s/logs" % (SURVEYS_URL, survey_id),
                    params={"page": 1, "page_size": 100},
                ),
                "获取移动端点位勘察操作日志",
            )
            logs = _assert_page_payload(logs_payload, "获取移动端点位勘察操作日志", 1, 100)
            actions = {item.get("action") for item in logs["items"]}
            assert {
                "create_survey",
                "create_school",
                "create_device",
                "create_position",
                "update_school",
                "update_device",
                "update_position",
            } <= actions, logs

            with allure.step("删除学校并校验设备点位被级联清除"):
                delete_payload = _assert_success(
                    mobile_site_survey_client.delete("%s/%s/schools/%s" % (SURVEYS_URL, survey_id, school["id"])),
                    "移动端删除勘察学校",
                )
            assert delete_payload["data"].get("id") == school["id"], delete_payload
            missing_device_response = mobile_site_survey_client.patch(
                "%s/%s/devices/%s" % (SURVEYS_URL, survey_id, device["id"]),
                json={"device_name": "不应更新"},
            )
            _assert_error_code(missing_device_response, "移动端删除学校后更新设备", NOT_FOUND_CODE)
            missing_position_response = mobile_site_survey_client.patch(
                "%s/%s/positions/%s" % (SURVEYS_URL, survey_id, position["id"]),
                json={"position_name": "不应更新"},
            )
            _assert_error_code(missing_position_response, "移动端删除学校后更新点位", NOT_FOUND_CODE)
        finally:
            _cleanup_survey_quietly(mobile_site_survey_client, survey_id)

    @allure.feature("Word 预览与导出")
    def test_移动端点位勘察_完整勘察预览导出记录与下载(self, mobile_site_survey_client):
        _require_write_tests()
        survey_id = None
        try:
            survey, _ = _create_temporary_survey(mobile_site_survey_client, "成功导出")
            survey_id = survey["id"]
            school, _, position = _create_complete_hierarchy(mobile_site_survey_client, survey_id)

            with allure.step("为完整勘察点位保存真实结构的现场照片元数据"):
                photo_payload = _assert_success(
                    mobile_site_survey_client.post(
                        "%s/%s/positions/%s/photos" % (SURVEYS_URL, survey_id, position["id"]),
                        json={
                            "original_file": _file_payload("AT-移动端导出原图.jpg", "export"),
                            "mark_type": "none",
                        },
                    ),
                    "移动端保存导出勘察照片",
                )
            assert isinstance(photo_payload["data"].get("id"), int), photo_payload

            with allure.step("校验完整勘察后允许导出"):
                validation_payload = _assert_success(
                    mobile_site_survey_client.post("%s/%s/validate" % (SURVEYS_URL, survey_id)),
                    "移动端校验可导出点位勘察",
                )
            validation = validation_payload["data"]
            assert validation.get("blockers") == [], validation
            assert validation.get("can_export") is True, validation

            with allure.step("生成单校 Word 预览，不创建导出记录"):
                preview_response = _get_binary(
                    mobile_site_survey_client,
                    "%s/%s/preview" % (SURVEYS_URL, survey_id),
                    params={"export_type": "school", "school_id": school["id"]},
                )
            _assert_docx_response(preview_response, "移动端预览单校点位勘察 Word", "inline")
            assert preview_response.headers.get("X-Site-Survey-Preview") == "transient", preview_response.headers

            with allure.step("使用创建时的过期版本导出，应明确提示版本冲突"):
                stale_export_response = mobile_site_survey_client.post(
                    "%s/%s/exports" % (SURVEYS_URL, survey_id),
                    json={"export_type": "project", "include_watermark": False, "version": survey["version"]},
                )
            stale_export = _assert_error_code(
                stale_export_response,
                "移动端使用过期版本导出项目点位勘察 Word",
                VERSION_CONFLICT_CODE,
            )
            assert (stale_export.get("data") or {}).get("current_version", 0) > survey["version"], stale_export

            with allure.step("刷新勘察单版本后导出无水印项目 Word 并记录下载地址"):
                current_payload = _assert_success(
                    mobile_site_survey_client.get("%s/%s" % (SURVEYS_URL, survey_id)),
                    "获取移动端导出前点位勘察详情",
                )
            current_survey = current_payload["data"]
            _assert_survey_shape(current_survey, "移动端导出前点位勘察详情", expected_survey_id=survey_id)
            export_payload = _assert_success(
                mobile_site_survey_client.post(
                    "%s/%s/exports" % (SURVEYS_URL, survey_id),
                    json={"export_type": "project", "include_watermark": False, "version": current_survey["version"]},
                ),
                "移动端导出项目点位勘察 Word",
            )
            export_data = export_payload["data"]
            export = export_data.get("export") or {}
            export_id = export.get("id")
            assert isinstance(export_id, int) and export_id > 0, export_payload
            assert export.get("survey_id") == survey_id, export
            assert export.get("export_type") == "project", export
            assert export.get("file_name", "").endswith(".docx"), export
            assert export_data.get("include_watermark") is False, export_data
            assert export_data.get("validation", {}).get("can_export") is True, export_data

            with allure.step("回查导出记录，并从下载地址读取真实 Word 文件"):
                exports_payload = _assert_success(
                    mobile_site_survey_client.get("%s/%s/exports" % (SURVEYS_URL, survey_id)),
                    "获取移动端点位勘察导出记录",
                )
            exports = (exports_payload["data"] or {}).get("items") or []
            exported = next((item for item in exports if item.get("id") == export_id), None)
            assert exported is not None, exports_payload
            assert exported.get("download_url") == export.get("download_url"), exported
            download_response = _get_binary(mobile_site_survey_client, exported["download_url"])
            _assert_docx_response(download_response, "下载移动端点位勘察 Word", "attachment")

            with allure.step("导出记录创建后勘察单状态更新为 exported"):
                detail_payload = _assert_success(
                    mobile_site_survey_client.get("%s/%s" % (SURVEYS_URL, survey_id)),
                    "回查移动端导出后点位勘察详情",
                )
            detail = detail_payload["data"]
            _assert_survey_shape(detail, "移动端导出后点位勘察详情", expected_survey_id=survey_id)
            assert detail.get("status") == "exported", detail
            assert detail.get("latest_export", {}).get("id") == export_id, detail
        finally:
            _cleanup_survey_quietly(mobile_site_survey_client, survey_id)

    @allure.feature("校验与导出异常")
    def test_移动端点位勘察_未完成勘察导出被阻断(self, mobile_site_survey_client):
        _require_write_tests()
        survey_id = None
        try:
            survey, _ = _create_temporary_survey(mobile_site_survey_client, "导出异常")
            survey_id = survey["id"]

            with allure.step("未添加学校时移动端校验返回阻断项"):
                validation_payload = _assert_success(
                    mobile_site_survey_client.post("%s/%s/validate" % (SURVEYS_URL, survey_id)),
                    "移动端校验未完成点位勘察",
                )
            validation = validation_payload["data"]
            assert validation.get("can_export") is False, validation
            assert any(item.get("code") == "school_required" for item in validation.get("blockers") or []), validation

            with allure.step("未完成勘察导出项目 Word 应被服务端阻断"):
                export_response = mobile_site_survey_client.post(
                    "%s/%s/exports" % (SURVEYS_URL, survey_id),
                    json={"export_type": "project", "include_watermark": True, "version": survey["version"]},
                )
            _assert_error_code(export_response, "移动端导出未完成点位勘察", EXPORT_BLOCKED_CODE)

            with allure.step("单校预览未选择学校应返回参数错误"):
                preview_response = mobile_site_survey_client.get(
                    "%s/%s/preview" % (SURVEYS_URL, survey_id),
                    params={"export_type": "school"},
                )
            _assert_error_code(preview_response, "移动端单校预览缺少学校", PARAM_ERROR_CODE)
        finally:
            _cleanup_survey_quietly(mobile_site_survey_client, survey_id)
