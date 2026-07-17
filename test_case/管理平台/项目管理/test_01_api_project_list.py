# -*- coding: utf-8 -*-
"""管理平台项目管理-项目列表接口自动化测试。

被测接口为 ``GET /v1/project-delivery/projects``。用例覆盖项目列表页面
使用的鉴权、分页、关键字、状态、负责人和风险筛选，以及列表记录进入详情后的
基础数据一致性。写入场景创建唯一的临时项目，并在测试结束时关闭并删除，避免
污染被测环境。
"""
from datetime import date, timedelta
import math
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, MANAGEMENT_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
PROJECTS_URL = "/v1/project-delivery/projects"
CUSTOMERS_URL = "/v1/customers"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
FORBIDDEN_CODE = 4030
NOT_FOUND_CODE = 4040
TOKEN_INVALID_CODE = 5104

PROJECT_STATUSES = {
    "delivering",
    "paused",
    "closed",
    "pending_acceptance",
    "rectifying",
    "delivered",
    "cancelled",
    "draft",
}
RISK_TYPES = {
    "material_missing",
    "node_overdue",
    "acceptance_blocked",
    "rectification_overdue",
    "demand_pending",
}
PROJECT_LIST_REQUIRED_FIELDS = {
    "id",
    "project_code",
    "project_name",
    "customer_name",
    "project_manager_id",
    "project_manager_name",
    "status",
    "status_text",
    "current_node_name",
    "progress",
    "material_complete_rate",
    "risks",
    "risk_texts",
    "version",
    "updated_at",
}
CUSTOMER_PICKER_REQUIRED_FIELDS = {"id", "name", "status", "channel_name"}


def _require_write_tests():
    """写操作仅在配置显式开启时执行。"""
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _parse_json(response, action):
    """将响应转换为 JSON，失败时输出定位所需的上下文。"""
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
    """校验统一成功响应；账号缺少项目查看权限时明确跳过。"""
    assert response.status_code == 200, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = _parse_json(response, action)
    if payload.get("code") == FORBIDDEN_CODE:
        pytest.skip("登录账号缺少 delivery:project:view 或 permission:manage 权限")
    assert payload.get("code") == SUCCESS_CODE, "%s 业务失败：%s" % (action, payload)
    assert "data" in payload, "%s 成功响应缺少 data：%s" % (action, payload)
    return payload


def _assert_page_payload(payload, action, expected_page=None, expected_page_size=None):
    """校验项目列表的统一分页外壳。"""
    data = payload["data"]
    assert isinstance(data, dict), "%s data 应为分页对象，实际为 %r" % (action, data)
    assert isinstance(data.get("items"), list), "%s data.items 应为数组：%s" % (action, data)
    assert isinstance(data.get("total"), int) and data["total"] >= 0, "%s total 非法：%s" % (action, data)
    assert isinstance(data.get("page"), int) and data["page"] >= 1, "%s page 非法：%s" % (action, data)
    assert isinstance(data.get("page_size"), int) and data["page_size"] >= 1, "%s page_size 非法：%s" % (action, data)
    assert isinstance(data.get("total_pages"), int) and data["total_pages"] >= 0, "%s total_pages 非法：%s" % (action, data)
    assert data["total_pages"] == math.ceil(data["total"] / data["page_size"]), "%s total_pages 计算错误：%s" % (action, data)
    assert len(data["items"]) <= data["page_size"], "%s 返回条数超过 page_size：%s" % (action, data)
    if expected_page is not None:
        assert data["page"] == expected_page, "%s 页码回显不正确：%s" % (action, data)
    if expected_page_size is not None:
        assert data["page_size"] == expected_page_size, "%s 每页数量回显不正确：%s" % (action, data)
    return data


def _assert_project_shape(project, action):
    """校验项目列表和详情共享的关键字段。"""
    assert isinstance(project, dict), "%s 项目项应为对象，实际为 %r" % (action, project)
    missing_fields = PROJECT_LIST_REQUIRED_FIELDS - set(project)
    assert not missing_fields, "%s 项目项缺少字段：%s；实际=%s" % (action, missing_fields, project)
    assert isinstance(project["id"], int) and project["id"] > 0, "%s 项目 id 非法：%s" % (action, project)
    assert isinstance(project["project_code"], str) and project["project_code"].strip(), "%s 项目编号为空：%s" % (action, project)
    assert isinstance(project["project_name"], str) and project["project_name"].strip(), "%s 项目名称为空：%s" % (action, project)
    assert isinstance(project["customer_name"], str) and project["customer_name"].strip(), "%s 客户名称为空：%s" % (action, project)
    assert project["status"] in PROJECT_STATUSES, "%s 项目状态异常：%s" % (action, project)
    assert isinstance(project["progress"], (int, float)) and 0 <= project["progress"] <= 100, "%s 项目进度非法：%s" % (action, project)
    assert isinstance(project["material_complete_rate"], (int, float)) and 0 <= project["material_complete_rate"] <= 100, "%s 资料完整度非法：%s" % (action, project)
    assert isinstance(project["risks"], list), "%s risks 应为数组：%s" % (action, project)
    assert set(project["risks"]) <= RISK_TYPES, "%s 返回未知风险类型：%s" % (action, project)
    assert isinstance(project["risk_texts"], list), "%s risk_texts 应为数组：%s" % (action, project)
    assert len(project["risk_texts"]) == len(project["risks"]), "%s 风险文本数量与风险数量不一致：%s" % (action, project)
    assert isinstance(project["version"], int) and project["version"] >= 1, "%s 项目版本号非法：%s" % (action, project)


def _assert_customer_page_payload(payload, action, expected_page=None, expected_page_size=None):
    """校验项目创建弹窗所用客户选择列表的分页结构。"""
    data = payload["data"]
    assert isinstance(data, dict), "%s data 应为分页对象，实际为 %r" % (action, data)
    assert isinstance(data.get("items"), list), "%s data.items 应为数组：%s" % (action, data)
    assert isinstance(data.get("total"), int) and data["total"] >= 0, "%s total 非法：%s" % (action, data)
    assert isinstance(data.get("page"), int) and data["page"] >= 1, "%s page 非法：%s" % (action, data)
    assert isinstance(data.get("page_size"), int) and data["page_size"] >= 1, "%s page_size 非法：%s" % (action, data)
    assert len(data["items"]) <= data["page_size"], "%s 返回条数超过 page_size：%s" % (action, data)
    if expected_page is not None:
        assert data["page"] == expected_page, "%s 页码回显不正确：%s" % (action, data)
    if expected_page_size is not None:
        assert data["page_size"] == expected_page_size, "%s 每页数量回显不正确：%s" % (action, data)
    return data


def _assert_customer_picker_shape(customer, action):
    """校验客户选择弹窗渲染所需的客户字段。"""
    assert isinstance(customer, dict), "%s 客户项应为对象，实际为 %r" % (action, customer)
    missing_fields = CUSTOMER_PICKER_REQUIRED_FIELDS - set(customer)
    assert not missing_fields, "%s 客户项缺少字段：%s；实际=%s" % (action, missing_fields, customer)
    assert isinstance(customer["id"], int) and customer["id"] > 0, "%s 客户 id 非法：%s" % (action, customer)
    assert isinstance(customer["name"], str) and customer["name"].strip(), "%s 客户名称为空：%s" % (action, customer)
    assert customer["status"] == "normal", "%s 客户选择器不应返回非正常客户：%s" % (action, customer)


def _close_and_delete_project(client, project_id):
    """将临时项目关闭后删除；删除失败必须暴露，避免遗留测试数据。"""
    close_payload = _assert_success(
        client.patch("%s/%s" % (PROJECTS_URL, project_id), json={"status": "closed"}),
        "关闭临时项目",
    )
    assert close_payload["data"].get("status") == "closed", "临时项目未成功关闭：%s" % close_payload
    delete_payload = _assert_success(
        client.delete("%s/%s" % (PROJECTS_URL, project_id)),
        "删除临时项目",
    )
    assert (delete_payload.get("data") or {}).get("id") == project_id, "删除临时项目返回异常：%s" % delete_payload


def _login_client(username, password):
    """登录管理平台，返回携带 Bearer Token 的专用客户端。"""
    client = HttpClient(headers=default_headers.copy())
    response = client.post(
        LOGIN_URL,
        json={"username": username, "password": password, "client_type": "pc"},
    )
    payload = _assert_success(response, "登录项目管理账号")
    token = (payload.get("data") or {}).get("access_token")
    assert token, "登录成功但 data.access_token 为空：%s" % payload
    client.headers["Authorization"] = "Bearer %s" % token
    return client


def _first_project(client):
    """获取一条可见项目，供筛选与详情校验复用。"""
    payload = _assert_success(
        client.get(PROJECTS_URL, params={"page": 1, "page_size": 1}),
        "获取项目列表（取样）",
    )
    data = _assert_page_payload(payload, "获取项目列表（取样）", expected_page=1, expected_page_size=1)
    return data["items"][0] if data["items"] else None


@pytest.fixture(scope="module")
def project_client():
    """登录管理平台并返回项目管理接口客户端。"""
    account = MANAGEMENT_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录管理平台")

    with allure.step("登录管理平台并获取项目管理 Token"):
        client = _login_client(username, password)
    yield client
    client.headers.pop("Authorization", None)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-项目管理-项目列表")
class Test项目列表访问控制:
    """验证项目列表鉴权与请求参数校验。"""

    @allure.feature("访问权限")
    def test_未登录访问项目列表_返回令牌无效(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Authorization 请求项目列表"):
            response = anonymous_client.get(PROJECTS_URL)
        assert response.status_code == 200, "统一鉴权异常应使用 HTTP 200：%s" % response.text
        payload = _parse_json(response, "未登录获取项目列表")
        assert payload.get("code") == TOKEN_INVALID_CODE, "未登录访问应返回令牌无效：%s" % payload

    @allure.feature("分页参数")
    def test_项目列表_非法页码被拒绝(self, project_client):
        with allure.step("传入不合法页码 page=0"):
            response = project_client.get(PROJECTS_URL, params={"page": 0, "page_size": 10})
        assert response.status_code == 200, "统一参数错误响应应使用 HTTP 200：%s" % response.text
        payload = _parse_json(response, "项目列表非法分页")
        assert payload.get("code") == INVALID_PARAMS_CODE, "非法分页应返回参数校验错误：%s" % payload
        assert isinstance(payload.get("data"), list) and payload["data"], "应返回字段错误详情：%s" % payload


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-项目管理-项目列表")
class Test项目列表查询:
    """验证项目列表页面的读取、筛选与详情跳转依赖的数据契约。"""

    @allure.feature("项目列表")
    def test_项目列表_分页结构与字段完整(self, project_client):
        with allure.step("按第一页、每页两条获取项目列表"):
            payload = _assert_success(
                project_client.get(PROJECTS_URL, params={"page": 1, "page_size": 2}),
                "获取项目列表",
            )
        data = _assert_page_payload(payload, "获取项目列表", expected_page=1, expected_page_size=2)
        for project in data["items"]:
            _assert_project_shape(project, "获取项目列表")

    @allure.feature("项目列表筛选")
    def test_项目列表_按关键字搜索命中原项目(self, project_client):
        project = _first_project(project_client)
        if project is None:
            pytest.skip("当前环境没有项目数据，无法验证关键字搜索")
        _assert_project_shape(project, "项目列表取样")

        with allure.step("按项目编号进行关键字搜索"):
            payload = _assert_success(
                project_client.get(
                    PROJECTS_URL,
                    params={"keyword": project["project_code"], "page": 1, "page_size": 20},
                ),
                "项目编号关键字搜索",
            )
        data = _assert_page_payload(payload, "项目编号关键字搜索", expected_page=1, expected_page_size=20)
        assert any(item.get("id") == project["id"] for item in data["items"]), (
            "关键字搜索结果未包含原项目。project=%s, result=%s" % (project, data)
        )

    @allure.feature("项目列表筛选")
    def test_项目列表_按状态和负责人筛选(self, project_client):
        project = _first_project(project_client)
        if project is None:
            pytest.skip("当前环境没有项目数据，无法验证状态和负责人筛选")
        _assert_project_shape(project, "项目列表取样")

        with allure.step("按取样项目状态筛选"):
            status_payload = _assert_success(
                project_client.get(
                    PROJECTS_URL,
                    params={"status": project["status"], "page": 1, "page_size": 100},
                ),
                "项目状态筛选",
            )
        status_data = _assert_page_payload(status_payload, "项目状态筛选", expected_page=1, expected_page_size=100)
        assert any(item.get("id") == project["id"] for item in status_data["items"]), "状态筛选未包含取样项目：%s" % status_data
        assert all(item.get("status") == project["status"] for item in status_data["items"]), "状态筛选返回了其他状态：%s" % status_data

        owner_id = project.get("project_manager_id")
        if not isinstance(owner_id, int) or owner_id <= 0:
            pytest.skip("取样项目未配置有效项目负责人，无法验证负责人筛选")
        with allure.step("按取样项目负责人筛选"):
            owner_payload = _assert_success(
                project_client.get(
                    PROJECTS_URL,
                    params={"owner_id": owner_id, "page": 1, "page_size": 100},
                ),
                "项目负责人筛选",
            )
        owner_data = _assert_page_payload(owner_payload, "项目负责人筛选", expected_page=1, expected_page_size=100)
        assert any(item.get("id") == project["id"] for item in owner_data["items"]), "负责人筛选未包含取样项目：%s" % owner_data
        assert all(item.get("project_manager_id") == owner_id for item in owner_data["items"]), "负责人筛选返回了其他负责人项目：%s" % owner_data

    @allure.feature("项目列表筛选")
    def test_项目列表_按风险筛选(self, project_client):
        payload = _assert_success(
            project_client.get(PROJECTS_URL, params={"page": 1, "page_size": 100}),
            "获取项目列表（风险取样）",
        )
        data = _assert_page_payload(payload, "获取项目列表（风险取样）", expected_page=1, expected_page_size=100)
        candidate = next((item for item in data["items"] if item.get("risks")), None)
        if candidate is None:
            pytest.skip("当前环境没有带风险的项目，无法验证风险筛选")
        _assert_project_shape(candidate, "风险项目取样")
        risk_type = candidate["risks"][0]

        with allure.step("按取样项目的风险类型筛选"):
            risk_payload = _assert_success(
                project_client.get(
                    PROJECTS_URL,
                    params={"risk_type": risk_type, "page": 1, "page_size": 100},
                ),
                "项目风险筛选",
            )
        risk_data = _assert_page_payload(risk_payload, "项目风险筛选", expected_page=1, expected_page_size=100)
        assert any(item.get("id") == candidate["id"] for item in risk_data["items"]), "风险筛选未包含取样项目：%s" % risk_data
        assert all(risk_type in item.get("risks", []) for item in risk_data["items"]), "风险筛选返回了不含目标风险的项目：%s" % risk_data

    @allure.feature("项目列表筛选")
    def test_项目列表_无匹配关键字返回空列表(self, project_client):
        keyword = "AT-NOT-FOUND-%s" % uuid4().hex
        with allure.step("按不存在的关键字搜索项目"):
            payload = _assert_success(
                project_client.get(
                    PROJECTS_URL,
                    params={"keyword": keyword, "page": 1, "page_size": 20},
                ),
                "项目空结果搜索",
            )
        data = _assert_page_payload(payload, "项目空结果搜索", expected_page=1, expected_page_size=20)
        assert data["total"] == 0 and data["items"] == [], "不存在的关键字应返回空列表：%s" % data

    @allure.feature("项目列表筛选")
    def test_项目列表_首页重点筛选结果正确(self, project_client):
        expectations = {
            "high_risk": lambda item: bool(item.get("risks")) or item.get("status") == "paused",
            "rectifying_focus": lambda item: item.get("status") == "rectifying" or "acceptance_blocked" in item.get("risks", []),
        }
        for filter_type, matches in expectations.items():
            with allure.step("按首页重点筛选 %s 获取项目" % filter_type):
                payload = _assert_success(
                    project_client.get(
                        PROJECTS_URL,
                        params={"filter_type": filter_type, "page": 1, "page_size": 100},
                    ),
                    "项目重点筛选 %s" % filter_type,
                )
            data = _assert_page_payload(payload, "项目重点筛选 %s" % filter_type, expected_page=1, expected_page_size=100)
            for project in data["items"]:
                _assert_project_shape(project, "项目重点筛选 %s" % filter_type)
                assert matches(project), "重点筛选 %s 返回了不符合条件的项目：%s" % (filter_type, project)

    @allure.feature("项目详情")
    def test_项目详情_与列表项目基础字段一致(self, project_client):
        project = _first_project(project_client)
        if project is None:
            pytest.skip("当前环境没有项目数据，无法验证项目详情")
        _assert_project_shape(project, "项目列表取样")

        with allure.step("获取列表取样项目的详情"):
            payload = _assert_success(
                project_client.get("%s/%s" % (PROJECTS_URL, project["id"])),
                "获取项目详情",
            )
        detail = payload["data"]
        _assert_project_shape(detail, "获取项目详情")
        for field in ("id", "project_code", "project_name", "customer_name", "status", "project_manager_id"):
            assert detail.get(field) == project.get(field), "项目详情字段 %s 与列表不一致：list=%s, detail=%s" % (field, project, detail)
        assert isinstance(detail.get("counts"), dict), "项目详情应返回 counts：%s" % detail


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-项目管理-项目列表")
class Test项目创建客户选择:
    """验证新建项目弹窗中客户/学校选择器的接口数据。"""

    @allure.feature("客户选择")
    def test_客户选择器_正常客户分页和字段完整(self, project_client):
        with allure.step("获取可选择的正常客户"):
            payload = _assert_success(
                project_client.get(
                    CUSTOMERS_URL,
                    params={"status": "normal", "page": 1, "page_size": 10},
                ),
                "获取正常客户列表",
            )
        data = _assert_customer_page_payload(payload, "获取正常客户列表", expected_page=1, expected_page_size=10)
        for customer in data["items"]:
            _assert_customer_picker_shape(customer, "获取正常客户列表")

    @allure.feature("客户选择")
    def test_客户选择器_按名称和渠道筛选(self, project_client):
        payload = _assert_success(
            project_client.get(
                CUSTOMERS_URL,
                params={"status": "normal", "page": 1, "page_size": 100},
            ),
            "获取正常客户列表（取样）",
        )
        data = _assert_customer_page_payload(payload, "获取正常客户列表（取样）", expected_page=1, expected_page_size=100)
        if not data["items"]:
            pytest.skip("当前环境没有正常客户，无法验证客户选择器筛选")
        customer = data["items"][0]
        _assert_customer_picker_shape(customer, "客户选择器取样")

        with allure.step("按取样客户名称筛选"):
            name_payload = _assert_success(
                project_client.get(
                    CUSTOMERS_URL,
                    params={"status": "normal", "name": customer["name"], "page": 1, "page_size": 100},
                ),
                "客户名称筛选",
            )
        name_data = _assert_customer_page_payload(name_payload, "客户名称筛选", expected_page=1, expected_page_size=100)
        assert any(item.get("id") == customer["id"] for item in name_data["items"]), "客户名称筛选未命中取样客户：%s" % name_data

        channel_customer = next((item for item in data["items"] if str(item.get("channel_name") or "").strip()), None)
        if channel_customer is None:
            pytest.skip("当前环境正常客户均未关联渠道，无法验证渠道名称筛选")
        with allure.step("按取样客户渠道名称筛选"):
            channel_payload = _assert_success(
                project_client.get(
                    CUSTOMERS_URL,
                    params={
                        "status": "normal",
                        "channel_name": channel_customer["channel_name"],
                        "page": 1,
                        "page_size": 100,
                    },
                ),
                "客户渠道名称筛选",
            )
        channel_data = _assert_customer_page_payload(channel_payload, "客户渠道名称筛选", expected_page=1, expected_page_size=100)
        assert any(item.get("id") == channel_customer["id"] for item in channel_data["items"]), "客户渠道名称筛选未命中取样客户：%s" % channel_data
        assert all(item.get("channel_name") == channel_customer["channel_name"] for item in channel_data["items"]), "客户渠道名称筛选返回了其他渠道客户：%s" % channel_data


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-项目管理-项目列表")
class Test项目创建流程:
    """验证项目列表页的新建项目校验和完整的可清理创建链路。"""

    @allure.feature("新建项目校验")
    def test_新建项目_必填项和字段边界被校验(self, project_client):
        _require_write_tests()
        invalid_cases = [
            ("缺少全部必填字段", {}),
            ("项目名称少于两个字符", {"project_name": "A", "customer_name": "自动化客户"}),
            ("客户名称少于两个字符", {"project_name": "自动化项目", "customer_name": "A"}),
            ("项目名称超过最大长度", {"project_name": "A" * 201, "customer_name": "自动化客户"}),
        ]
        for case_name, body in invalid_cases:
            with allure.step("校验%s" % case_name):
                response = project_client.post(PROJECTS_URL, json=body)
            assert response.status_code == 200, "%s HTTP 状态异常：%s" % (case_name, response.text)
            payload = _parse_json(response, "新建项目%s" % case_name)
            if payload.get("code") == FORBIDDEN_CODE:
                pytest.skip("登录账号缺少 delivery:project:create 或 permission:manage 权限")
            assert payload.get("code") == INVALID_PARAMS_CODE, "%s 应返回参数校验错误：%s" % (case_name, payload)
            assert isinstance(payload.get("data"), list) and payload["data"], "%s 应返回字段错误详情：%s" % (case_name, payload)

    @allure.feature("新建项目")
    def test_新建项目_列表回查详情关闭并删除(self, project_client):
        _require_write_tests()
        project_id = None
        deleted = False
        project_name = "AT-项目列表-%s" % uuid4().hex[:12]
        customer_name = "AT-项目客户-%s" % uuid4().hex[:8]
        body = {
            "project_name": project_name,
            "customer_name": customer_name,
            "contract_no": "AT-CONTRACT-%s" % uuid4().hex[:8],
            "contract_summary": "项目列表接口自动化临时项目",
            "is_external_purchase": True,
            "planned_start_date": date.today().isoformat(),
            "planned_end_date": (date.today() + timedelta(days=7)).isoformat(),
            "remark": "AT-项目列表自动化测试数据，可安全删除",
        }
        try:
            with allure.step("创建带唯一标识的临时项目"):
                create_payload = _assert_success(project_client.post(PROJECTS_URL, json=body), "创建临时项目")
            project = create_payload["data"]
            _assert_project_shape(project, "创建临时项目")
            project_id = project["id"]
            assert project["project_name"] == project_name, "创建后的项目名称不正确：%s" % project
            assert project["customer_name"] == customer_name, "创建后的客户名称不正确：%s" % project
            assert project["is_external_purchase"] is True, "创建后的外采标记不正确：%s" % project

            with allure.step("按新建项目名称回查项目列表"):
                list_payload = _assert_success(
                    project_client.get(
                        PROJECTS_URL,
                        params={"keyword": project_name, "page": 1, "page_size": 20},
                    ),
                    "回查新建项目列表",
                )
            list_data = _assert_page_payload(list_payload, "回查新建项目列表", expected_page=1, expected_page_size=20)
            assert any(item.get("id") == project_id for item in list_data["items"]), "项目列表未包含新建项目：%s" % list_data

            with allure.step("获取新建项目详情"):
                detail_payload = _assert_success(
                    project_client.get("%s/%s" % (PROJECTS_URL, project_id)),
                    "获取新建项目详情",
                )
            detail = detail_payload["data"]
            _assert_project_shape(detail, "获取新建项目详情")
            assert detail["project_name"] == project_name and detail["customer_name"] == customer_name, "新建项目详情与提交数据不一致：%s" % detail

            with allure.step("关闭并删除临时项目"):
                _close_and_delete_project(project_client, project_id)
            deleted = True

            with allure.step("删除后查询项目详情应返回不存在"):
                response = project_client.get("%s/%s" % (PROJECTS_URL, project_id))
            assert response.status_code == 200, "删除后查询 HTTP 状态异常：%s" % response.text
            payload = _parse_json(response, "删除后查询临时项目")
            assert payload.get("code") == NOT_FOUND_CODE, "删除后项目仍可查询：%s" % payload
        finally:
            if project_id and not deleted:
                with allure.step("失败兜底：关闭并删除临时项目"):
                    _close_and_delete_project(project_client, project_id)
