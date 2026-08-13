# -*- coding: utf-8 -*-
"""移动端项目交付接口自动化测试。

接口契约来源于 ``canteen_operate_platfrom_app`` 的项目交付模块：

- ``project_delivery_request.dart``：待办、项目、节点、资料、整改和需求接口。
- ``delivery_todo_controller.dart``：按所有待办及类型汇总加载任务。
- ``node_submit_controller.dart``、``node_confirm_controller.dart``：资料版本、验收确认和驳回。
- ``rectification_submit_controller.dart``、``demand_create_controller.dart``：整改提交和需求登记。

写操作会创建 ``AT-移动端项目交付-`` 前缀的独立项目，全部项目数据均在用例结束时关闭
并删除；不会操作环境已有的交付项目、节点、资料、整改或需求。
"""
from datetime import date, datetime, timedelta
from uuid import uuid4

import allure
import pytest
import requests

from config.project_information import ENABLE_WRITE_TESTS, MOBILE_TEST_ACCOUNT, default_headers
from utils.http_client import NO_PROXIES, HttpClient


LOGIN_URL = "/v1/login"
PROJECTS_URL = "/v1/project-delivery/projects"
TODOS_URL = "/v1/project-delivery/todos"
DASHBOARD_SUMMARY_URL = "/v1/project-delivery/dashboard/summary"
DASHBOARD_RISKS_URL = "/v1/project-delivery/dashboard/risks"
MEMBER_CANDIDATES_URL = "/v1/project-delivery/member-candidates"
PERMISSION_MATRIX_URL = "/v1/project-delivery/permissions/matrix"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
PARAM_ERROR_CODE = 4100
FORBIDDEN_CODE = 4030
TOKEN_INVALID_CODE = 5104
STATE_CONFLICT_CODE = 409010
GATE_BLOCKED_CODE = 409020
NOT_FOUND_CODE = 4040

PROJECT_TODO_TYPES = {"node", "confirm", "material", "rectification", "demand"}
TODO_TYPES = PROJECT_TODO_TYPES | {"team_plan", "after_sales"}
TODO_SOURCES = {"project_list", "team_plan", "after_sales", "demand"}
TODO_STATUSES = {"open", "closed"}
NODE_STATUSES = {"pending", "in_progress", "submitted", "confirmed", "rejected", "blocked", "skipped"}
PROJECT_REQUIRED_FIELDS = {
    "id",
    "project_code",
    "project_name",
    "customer_name",
    "status",
    "current_node_id",
    "current_node_name",
    "progress",
    "material_complete_rate",
    "version",
}
TODO_REQUIRED_FIELDS = {
    "id",
    "project_id",
    "project_name",
    "customer_name",
    "owner_name",
    "title",
    "todo_type",
    "source_type",
    "status",
    "priority",
    "overdue",
}
NODE_REQUIRED_FIELDS = {
    "id",
    "project_id",
    "node_name",
    "phase",
    "sort_order",
    "status",
    "owner_name",
    "requires_confirmation",
    "requires_material_gate",
    "version",
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
        pytest.skip("测试账号缺少移动端项目交付所需权限")
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


def _assert_error(response, action, expected_code, expected_message, expected_http_status=200):
    payload = _assert_error_code(response, action, expected_code, expected_http_status)
    assert payload.get("msg") == expected_message, "%s 错误信息不正确：%s" % (action, payload)
    return payload


def _assert_page_payload(payload, action, expected_page, expected_page_size):
    data = payload["data"]
    assert isinstance(data, dict), "%s data 应为分页对象：%s" % (action, data)
    assert isinstance(data.get("items"), list), "%s data.items 应为数组：%s" % (action, data)
    assert isinstance(data.get("total"), int) and data["total"] >= 0, "%s data.total 非法：%s" % (action, data)
    assert data.get("page") == expected_page, "%s 页码回显不正确：%s" % (action, data)
    assert data.get("page_size") == expected_page_size, "%s 每页数量回显不正确：%s" % (action, data)
    assert len(data["items"]) <= expected_page_size, "%s 返回条数超过 page_size：%s" % (action, data)
    return data


def _assert_project_shape(project, action):
    assert isinstance(project, dict), "%s 项目应为对象：%r" % (action, project)
    missing = PROJECT_REQUIRED_FIELDS - set(project)
    assert not missing, "%s 项目缺少字段 %s：%s" % (action, missing, project)
    assert isinstance(project["id"], int) and project["id"] > 0, "%s 项目 id 非法：%s" % (action, project)
    assert isinstance(project["project_code"], str) and project["project_code"], "%s 项目编号为空：%s" % (action, project)
    assert isinstance(project["project_name"], str) and project["project_name"], "%s 项目名称为空：%s" % (action, project)
    assert isinstance(project["customer_name"], str) and project["customer_name"], "%s 客户名称为空：%s" % (action, project)
    assert isinstance(project["progress"], (int, float)) and 0 <= project["progress"] <= 100, "%s 项目进度非法：%s" % (action, project)
    assert isinstance(project["material_complete_rate"], (int, float)) and 0 <= project["material_complete_rate"] <= 100, "%s 资料完整率非法：%s" % (action, project)
    assert isinstance(project["version"], int) and project["version"] >= 1, "%s 项目版本号非法：%s" % (action, project)


def _assert_todo_shape(todo, action):
    assert isinstance(todo, dict), "%s 待办应为对象：%r" % (action, todo)
    missing = TODO_REQUIRED_FIELDS - set(todo)
    assert not missing, "%s 待办缺少字段 %s：%s" % (action, missing, todo)
    todo_source = todo.get("todo_source")
    assert todo_source in TODO_SOURCES, "%s 待办来源非法：%s" % (action, todo)
    assert todo["todo_type"] in TODO_TYPES, "%s 待办类型非法：%s" % (action, todo)
    assert todo["status"] in TODO_STATUSES, "%s 待办状态非法：%s" % (action, todo)
    assert isinstance(todo["overdue"], bool), "%s overdue 应为布尔值：%s" % (action, todo)

    if todo_source == "project_list":
        assert todo["todo_type"] in PROJECT_TODO_TYPES, "%s 项目待办类型非法：%s" % (action, todo)
        assert isinstance(todo["id"], int) and todo["id"] > 0, "%s 项目待办 id 非法：%s" % (action, todo)
        assert isinstance(todo["project_id"], int) and todo["project_id"] > 0, "%s 项目待办项目 id 非法：%s" % (action, todo)
        return

    source_id = todo.get("source_id")
    assert isinstance(source_id, int) and source_id > 0, "%s 聚合待办来源 id 非法：%s" % (action, todo)
    assert todo["id"] == "%s:%s" % (todo_source, source_id), "%s 聚合待办 id 不正确：%s" % (action, todo)
    assert todo.get("todo_key") == todo["id"], "%s 聚合待办 key 不正确：%s" % (action, todo)
    if todo_source in {"team_plan", "after_sales"}:
        assert todo["project_id"] is None, "%s 非项目待办不应关联项目：%s" % (action, todo)
    else:
        assert isinstance(todo["project_id"], int) and todo["project_id"] > 0, "%s 需求待办项目 id 非法：%s" % (action, todo)


def _assert_node_shape(node, action):
    assert isinstance(node, dict), "%s 节点应为对象：%r" % (action, node)
    missing = NODE_REQUIRED_FIELDS - set(node)
    assert not missing, "%s 节点缺少字段 %s：%s" % (action, missing, node)
    assert isinstance(node["id"], int) and node["id"] > 0, "%s 节点 id 非法：%s" % (action, node)
    assert isinstance(node["project_id"], int) and node["project_id"] > 0, "%s 节点项目 id 非法：%s" % (action, node)
    assert node["status"] in NODE_STATUSES, "%s 节点状态非法：%s" % (action, node)
    assert isinstance(node["version"], int) and node["version"] >= 1, "%s 节点版本号非法：%s" % (action, node)


def _login_mobile_client(username, password):
    client = HttpClient(headers=default_headers.copy())
    response = client.post(
        LOGIN_URL,
        json={"username": username, "password": password, "client_type": "mobile"},
    )
    payload = _assert_success(response, "移动端项目交付账号登录")
    data = payload.get("data") or {}
    token = data.get("access_token")
    assert token, "移动端登录成功但未返回 access_token：%s" % payload
    user_info = data.get("user_info") or {}
    user_id = user_info.get("id")
    assert isinstance(user_id, int) and user_id > 0, "移动端登录成功但未返回当前用户 id：%s" % payload
    user_keyword = str(
        user_info.get("user_id") or user_info.get("email") or user_info.get("phone") or ""
    ).strip()
    assert user_keyword, "移动端登录成功但未返回当前用户检索信息：%s" % payload
    client.headers["Authorization"] = "Bearer %s" % token
    client.mobile_user_id = user_id
    client.mobile_user_keyword = user_keyword
    return client


@pytest.fixture(scope="module")
def mobile_delivery_client():
    """移动端与管理平台共用统一的本地/CI 测试账号。"""
    account = MOBILE_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录移动端项目交付")

    with allure.step("使用 client_type=mobile 登录并获取项目交付 Token"):
        client = _login_mobile_client(username, password)
    yield client
    client.headers.pop("Authorization", None)


def _mobile_request_meta():
    """ProjectDeliveryRequest 写接口会携带的移动端请求标识。"""
    return {"source_client": "mobile", "request_id": str(uuid4())}


def _create_temporary_project(client, scenario):
    name = "AT-移动端项目交付-%s-%s" % (scenario, uuid4().hex[:10])
    body = {
        "project_name": name,
        "customer_name": "AT-移动端交付客户-%s" % uuid4().hex[:8],
        "contract_no": "AT-MOBILE-PD-%s" % uuid4().hex[:8],
        "contract_summary": "移动端项目交付接口自动化临时项目",
        "is_external_purchase": True,
        "planned_start_date": date.today().isoformat(),
        "planned_end_date": (date.today() + timedelta(days=14)).isoformat(),
        "remark": "移动端项目交付自动化数据，可安全删除",
    }
    payload = _assert_success(client.post(PROJECTS_URL, json=body), "创建移动端项目交付临时项目")
    project = payload["data"]
    _assert_project_shape(project, "创建移动端项目交付临时项目")
    assert project["project_name"] == name, project
    return project


def _close_and_delete_project(client, project_id):
    close_payload = _assert_success(
        client.patch("%s/%s" % (PROJECTS_URL, project_id), json={"status": "closed"}),
        "关闭移动端项目交付临时项目",
    )
    assert close_payload["data"].get("status") == "closed", close_payload
    delete_payload = _assert_success(
        client.delete("%s/%s" % (PROJECTS_URL, project_id)),
        "删除移动端项目交付临时项目",
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


def _get_nodes(client, project_id):
    payload = _assert_success(client.get("%s/%s/nodes" % (PROJECTS_URL, project_id)), "获取移动端项目节点")
    data = payload["data"]
    assert isinstance(data, dict) and isinstance(data.get("items"), list), "节点列表格式不正确：%s" % payload
    for node in data["items"]:
        _assert_node_shape(node, "移动端项目节点列表")
    assert data["items"], "新建项目未初始化交付节点：%s" % payload
    return data["items"]


def _get_node_detail(client, project_id, node_id):
    payload = _assert_success(
        client.get("%s/%s/nodes/%s" % (PROJECTS_URL, project_id, node_id)),
        "获取移动端节点任务详情",
    )
    data = payload["data"]
    assert isinstance(data, dict), "移动端节点任务详情格式不正确：%s" % payload
    _assert_node_shape(data.get("node"), "移动端节点任务详情")
    assert isinstance(data.get("materials"), list), "节点任务资料应为数组：%s" % data
    assert isinstance(data.get("logs"), list), "节点任务日志应为数组：%s" % data
    return data


def _list_todos(client, todo_type="all", page=1, page_size=100):
    payload = _assert_success(
        client.get(
            TODOS_URL,
            params={"status": "open", "todo_type": todo_type, "page": page, "page_size": page_size},
        ),
        "获取移动端%s待办" % todo_type,
    )
    data = _assert_page_payload(payload, "获取移动端%s待办" % todo_type, page, page_size)
    for todo in data["items"]:
        _assert_todo_shape(todo, "移动端待办列表")
        if todo_type == "project_todo":
            assert todo["todo_source"] == "project_list", "项目待办筛选返回其他来源：%s" % todo
        elif todo_type != "all":
            assert todo["todo_type"] == todo_type, "待办类型筛选返回其他类型：%s" % todo
    return data


def _find_project_todo(client, project_id, todo_type):
    data = _list_todos(client, todo_type=todo_type)
    matched = next((todo for todo in data["items"] if todo.get("project_id") == project_id), None)
    assert matched is not None, "移动端%s待办列表未包含临时项目 %s：%s" % (todo_type, project_id, data)
    return matched


def _get_member_candidate(client):
    """选择非当前登录用户的真实候选成员，不创建或修改系统用户。"""
    payload = _assert_success(
        client.get(MEMBER_CANDIDATES_URL, params={"page": 1, "page_size": 100}),
        "获取移动端项目成员候选人",
    )
    data = _assert_page_payload(payload, "获取移动端项目成员候选人", 1, 100)
    current_user_id = getattr(client, "mobile_user_id", None)
    candidate = next(
        (item for item in data["items"] if item.get("id") != current_user_id),
        None,
    )
    if candidate is None:
        pytest.skip("当前环境没有可用于项目成员 CRUD 的其他活跃用户")
    assert isinstance(candidate.get("id"), int) and candidate["id"] > 0, candidate
    assert isinstance(candidate.get("roles"), list), candidate
    return candidate


def _upload_mobile_delivery_file(client, file_name, folder="project_delivery_material"):
    """按 uploadPickedImages/uploadPlatformFiles 的 multipart 请求上传临时文件。"""
    headers = {
        key: value
        for key, value in client.headers.items()
        if key.lower() != "content-type"
    }
    response = requests.post(
        client._url("/v1/upload"),
        data={"folder": folder},
        files={"files": (file_name, b"mobile project delivery api test", "text/plain")},
        headers=headers,
        timeout=client.timeout,
        proxies=NO_PROXIES,
    )
    payload = _assert_success(response, "移动端上传项目交付资料文件")
    files = (payload.get("data") or {}).get("files") or []
    assert len(files) == 1 and isinstance(files[0], dict), "移动端上传文件返回格式不正确：%s" % payload
    uploaded = files[0]
    assert uploaded.get("name") == file_name, "移动端上传文件名称不正确：%s" % uploaded
    assert uploaded.get("download_url") or uploaded.get("url"), "移动端上传文件缺少访问地址：%s" % uploaded
    return uploaded


def _create_material_version(client, project_id, material_id, file_name, version_note, uploaded_file=None):
    """按 DeliveryUploadedFile.toMaterialVersionJson 调用移动端资料版本接口。"""
    uploaded_file = uploaded_file or {}
    attachment_id = (
        uploaded_file.get("object_name")
        or uploaded_file.get("local_path")
        or uploaded_file.get("id")
        or "https://example.com/%s" % file_name
    )
    download_url = uploaded_file.get("download_url") or uploaded_file.get("url") or "https://example.com/%s" % file_name
    file_size = uploaded_file.get("size") or uploaded_file.get("file_size") or 12
    payload = _assert_success(
        client.post(
            "%s/%s/materials/%s/versions" % (PROJECTS_URL, project_id, material_id),
            json={
                "attachment_id": attachment_id,
                "file_name": file_name,
                "file_size": file_size,
                "download_url": download_url,
                "version_note": version_note,
                **_mobile_request_meta(),
            },
        ),
        "移动端上传项目资料版本",
    )
    material = payload["data"]
    assert isinstance(material, dict) and material.get("id") == material_id, payload
    assert material.get("status") == "uploaded", payload
    return material


def _prepare_submitted_confirm_node(client, project_id):
    """为确认页准备一个 submitted 节点；跳过非确认节点仅用于隔离测试项目。"""
    for _ in range(20):
        project_payload = _assert_success(
            client.get("%s/%s" % (PROJECTS_URL, project_id)),
            "获取移动端项目详情",
        )
        project = project_payload["data"]
        current_node_id = project.get("current_node_id")
        if not current_node_id:
            pytest.skip("交付模板没有可用于移动端验收确认的节点")
        node_detail = _get_node_detail(client, project_id, current_node_id)
        node = node_detail["node"]
        if not node.get("requires_confirmation"):
            _assert_success(
                client.post(
                    "%s/%s/nodes/%s/skip" % (PROJECTS_URL, project_id, current_node_id),
                    json={"reason": "自动化准备移动端验收确认节点"},
                ),
                "跳过非确认节点",
            )
            continue

        for material in node_detail["materials"]:
            if material.get("is_required"):
                _create_material_version(
                    client,
                    project_id,
                    material["id"],
                    "AT-移动端确认节点资料-%s.txt" % uuid4().hex[:8],
                    "移动端确认节点测试资料",
                )

        submit_payload = _assert_success(
            client.post(
                "%s/%s/nodes/%s/submit" % (PROJECTS_URL, project_id, current_node_id),
                json={
                    "result": "completed",
                    "remark": "自动化准备移动端节点确认状态",
                    "client_version": node["version"],
                },
            ),
            "准备已提交节点",
        )
        submitted = submit_payload["data"]
        _assert_node_shape(submitted, "准备已提交节点")
        if submitted.get("status") != "submitted":
            pytest.skip("当前交付模板的确认节点未进入 submitted 状态：%s" % submitted)
        return submitted
    pytest.skip("交付模板没有可进入移动端确认页的节点")


@allure.parent_suite("接口自动化")
@allure.suite("移动端-项目交付")
class Test移动端项目交付待办:
    """覆盖移动端待办首页的鉴权、分页和类型汇总查询。"""

    @allure.feature("移动端鉴权")
    def test_未登录访问移动端项目待办_返回令牌无效(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Token 请求项目交付待办"):
            response = anonymous_client.get(TODOS_URL, params={"status": "open", "todo_type": "all", "page": 1, "page_size": 20})
        _assert_error_code(response, "未登录获取移动端项目待办", TOKEN_INVALID_CODE)

    @allure.feature("待办列表与汇总")
    def test_移动端项目待办_分页和六种汇总类型查询(self, mobile_delivery_client):
        with allure.step("加载项目交付待办首页"):
            _list_todos(mobile_delivery_client, todo_type="all", page=1, page_size=20)

        with allure.step("模拟移动端汇总卡片分别查询各待办类型"):
            for todo_type in ("node", "confirm", "material", "rectification", "demand"):
                _list_todos(mobile_delivery_client, todo_type=todo_type, page=1, page_size=100)

    @allure.feature("参数校验")
    def test_移动端项目待办_非法页码被拒绝(self, mobile_delivery_client):
        with allure.step("移动端传入非法待办页码"):
            response = mobile_delivery_client.get(TODOS_URL, params={"status": "open", "todo_type": "all", "page": 0, "page_size": 20})
        _assert_error_code(response, "移动端项目待办非法页码", INVALID_PARAMS_CODE)

    @allure.feature("项目异常")
    def test_移动端项目交付_创建参数与不存在项目校验(self, mobile_delivery_client):
        _require_write_tests()
        invalid_projects = [
            ("缺少全部必填字段", {}),
            ("项目名称少于两个字符", {"project_name": "A", "customer_name": "自动化客户"}),
            ("客户名称少于两个字符", {"project_name": "自动化项目", "customer_name": "A"}),
        ]
        for action, body in invalid_projects:
            with allure.step("移动端项目交付创建校验：%s" % action):
                response = mobile_delivery_client.post(PROJECTS_URL, json=body)
            _assert_error_code(response, "移动端项目交付%s" % action, INVALID_PARAMS_CODE)

        with allure.step("移动端查询不存在的项目交付详情"):
            missing_response = mobile_delivery_client.get("%s/%s" % (PROJECTS_URL, 2147483647))
        _assert_error_code(missing_response, "移动端查询不存在项目", NOT_FOUND_CODE)

    @allure.feature("交付看板与权限")
    def test_移动端项目交付_看板风险成员候选人与权限矩阵查询(self, mobile_delivery_client):
        """只读覆盖交付工作台加载所依赖的管理接口。"""
        with allure.step("加载项目交付看板统计"):
            summary_payload = _assert_success(
                mobile_delivery_client.get(DASHBOARD_SUMMARY_URL),
                "获取移动端项目交付看板统计",
            )
        summary = summary_payload["data"]
        assert isinstance(summary, dict), summary
        metrics = summary.get("metrics")
        assert isinstance(metrics, dict), summary
        expected_metric_keys = {
            "total_projects",
            "delivering",
            "pending_acceptance",
            "rectifying",
            "delivered",
            "material_complete_rate",
        }
        assert expected_metric_keys <= set(metrics), summary
        assert all(isinstance(metrics[key], (int, float)) for key in expected_metric_keys), summary
        assert 0 <= metrics["material_complete_rate"] <= 100, summary
        assert isinstance(summary.get("status_distribution"), list), summary
        assert isinstance(summary.get("phase_distribution"), list), summary
        assert isinstance(summary.get("risk_distribution"), list), summary
        trend = summary.get("node_due_trend")
        assert isinstance(trend, list) and len(trend) == 7, summary
        assert all({"date", "label", "count"} <= set(item) for item in trend), trend

        with allure.step("按高风险筛选加载项目交付风险列表"):
            risks_payload = _assert_success(
                mobile_delivery_client.get(
                    DASHBOARD_RISKS_URL,
                    params={"filter_type": "high_risk", "page": 1, "page_size": 20},
                ),
                "获取移动端项目交付风险列表",
            )
        risks = _assert_page_payload(risks_payload, "获取移动端项目交付风险列表", 1, 20)
        for project in risks["items"]:
            _assert_project_shape(project, "移动端项目交付风险项目")
            assert "primary_risk" in project and "primary_risk_text" in project, project

        with allure.step("加载项目成员选择器候选人"):
            candidates_payload = _assert_success(
                mobile_delivery_client.get(MEMBER_CANDIDATES_URL, params={"page": 1, "page_size": 20}),
                "获取移动端项目成员候选人",
            )
        candidates = _assert_page_payload(candidates_payload, "获取移动端项目成员候选人", 1, 20)
        for candidate in candidates["items"]:
            assert isinstance(candidate.get("id"), int) and candidate["id"] > 0, candidate
            assert isinstance(candidate.get("roles"), list), candidate

        with allure.step("读取项目交付角色权限矩阵"):
            matrix_payload = _assert_success(
                mobile_delivery_client.get(PERMISSION_MATRIX_URL),
                "获取移动端项目交付权限矩阵",
            )
        matrix = matrix_payload["data"]
        assert isinstance(matrix, dict), matrix
        roles = matrix.get("roles")
        permissions = matrix.get("permissions")
        assignments = matrix.get("matrix")
        assert isinstance(roles, list) and roles, matrix
        assert isinstance(permissions, list) and permissions, matrix
        assert isinstance(assignments, dict), matrix
        role_ids = {str(item["id"]) for item in roles}
        assert role_ids <= set(assignments), matrix
        assert all(str(item.get("code") or "").startswith(("delivery:", "after_sales:", "menu:")) for item in permissions), matrix


@allure.parent_suite("接口自动化")
@allure.suite("移动端-项目交付")
class Test移动端项目交付处理链路:
    """覆盖移动端节点、资料、整改、需求和验收确认操作。"""

    @allure.feature("节点任务详情")
    def test_移动端项目交付_项目创建关闭删除完整链路(self, mobile_delivery_client):
        """显式验证自动化临时项目的创建、读取、关闭、删除和删除后不存在。"""
        _require_write_tests()
        project_id = None
        try:
            with allure.step("创建移动端项目交付临时项目"):
                project = _create_temporary_project(mobile_delivery_client, "创建删除")
            project_id = project["id"]

            with allure.step("回查项目详情、节点和初始待办"):
                detail_payload = _assert_success(
                    mobile_delivery_client.get("%s/%s" % (PROJECTS_URL, project_id)),
                    "移动端回查新建项目详情",
                )
                _assert_project_shape(detail_payload["data"], "移动端回查新建项目详情")
                _get_nodes(mobile_delivery_client, project_id)
                _find_project_todo(mobile_delivery_client, project_id, "node")

            with allure.step("关闭并删除移动端项目交付临时项目"):
                _close_and_delete_project(mobile_delivery_client, project_id)
            deleted_project_id = project_id
            project_id = None

            with allure.step("删除后项目详情返回不存在"):
                missing_response = mobile_delivery_client.get("%s/%s" % (PROJECTS_URL, deleted_project_id))
            _assert_error_code(missing_response, "移动端删除后查询项目", NOT_FOUND_CODE)
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("节点异常")
    def test_移动端节点确认_未提交节点产生状态冲突(self, mobile_delivery_client):
        """确认页只能操作 submitted 节点；in_progress 节点应返回明确状态冲突。"""
        _require_write_tests()
        project_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "节点异常")
            project_id = project["id"]
            current_node = next(
                item for item in _get_nodes(mobile_delivery_client, project_id)
                if item["id"] == project["current_node_id"]
            )
            assert current_node["status"] == "in_progress", current_node

            with allure.step("移动端直接确认未提交节点"):
                response = mobile_delivery_client.post(
                    "%s/%s/nodes/%s/confirm" % (PROJECTS_URL, project_id, current_node["id"]),
                    json={"remark": "不应确认", "client_version": current_node["version"], **_mobile_request_meta()},
                )
            _assert_error_code(response, "移动端确认未提交节点", STATE_CONFLICT_CODE)
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("节点任务详情")
    def test_移动端项目待办_项目节点详情与节点待办一致(self, mobile_delivery_client):
        _require_write_tests()
        project_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "节点详情")
            project_id = project["id"]
            nodes = _get_nodes(mobile_delivery_client, project_id)
            current_node = next((item for item in nodes if item.get("id") == project.get("current_node_id")), None)
            assert current_node is not None, "项目当前节点不在节点列表：%s" % nodes

            with allure.step("打开移动端节点待办详情"):
                detail = _get_node_detail(mobile_delivery_client, project_id, current_node["id"])
            assert detail["node"]["id"] == current_node["id"], detail
            assert detail["node"]["project_id"] == project_id, detail

            with allure.step("待办首页按节点处理类型回查新项目任务"):
                todo = _find_project_todo(mobile_delivery_client, project_id, "node")
            assert todo.get("source_type") == "node", todo
            assert todo.get("source_id") == current_node["id"], todo

            _close_and_delete_project(mobile_delivery_client, project_id)
            project_id = None
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("项目成员与日志")
    def test_移动端项目交付_节点编辑项目成员管理和日志回查(self, mobile_delivery_client):
        _require_write_tests()
        project_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "成员与日志")
            project_id = project["id"]
            node = next(item for item in _get_nodes(mobile_delivery_client, project_id) if item["id"] == project["current_node_id"])
            candidate = _get_member_candidate(mobile_delivery_client)

            with allure.step("编辑当前交付节点的负责人、截止时间和备注"):
                due_at = (datetime.now() + timedelta(days=3)).replace(microsecond=0).isoformat()
                node_update_payload = _assert_success(
                    mobile_delivery_client.patch(
                        "%s/%s/nodes/%s" % (PROJECTS_URL, project_id, node["id"]),
                        json={
                            "owner_id": mobile_delivery_client.mobile_user_id,
                            "due_at": due_at,
                            "remark": "AT-移动端项目交付节点编辑",
                        },
                    ),
                    "移动端编辑项目交付节点",
                )
            updated_node = node_update_payload["data"]
            _assert_node_shape(updated_node, "移动端编辑项目交付节点")
            assert updated_node.get("owner_id") == mobile_delivery_client.mobile_user_id, updated_node
            assert updated_node.get("due_at", "").startswith(due_at[:16]), updated_node
            assert updated_node.get("version") == node["version"] + 1, updated_node

            with allure.step("将现有候选人加入临时项目"):
                add_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/members" % (PROJECTS_URL, project_id),
                        json={
                            "user_id": candidate["id"],
                            "project_role": "member",
                            "node_scope": "当前节点",
                            "material_permission": "read",
                        },
                    ),
                    "移动端添加项目成员",
                )
            member_id = (add_payload.get("data") or {}).get("id")
            assert isinstance(member_id, int) and member_id > 0, add_payload

            with allure.step("更新临时项目成员职责和资料权限"):
                update_member_payload = _assert_success(
                    mobile_delivery_client.patch(
                        "%s/%s/members/%s" % (PROJECTS_URL, project_id, member_id),
                        json={
                            "project_role": "reviewer",
                            "node_scope": "全部节点",
                            "material_permission": "write",
                            "is_active": True,
                        },
                    ),
                    "移动端更新项目成员",
                )
            assert (update_member_payload.get("data") or {}).get("id") == member_id, update_member_payload

            with allure.step("回查成员列表中的更新结果"):
                members_payload = _assert_success(
                    mobile_delivery_client.get("%s/%s/members" % (PROJECTS_URL, project_id)),
                    "获取移动端项目成员列表",
                )
            members = (members_payload["data"] or {}).get("items") or []
            member = next((item for item in members if item.get("id") == member_id), None)
            assert member is not None, members_payload
            assert member.get("user_id") == candidate["id"], member
            assert member.get("project_role") == "reviewer", member
            assert member.get("node_scope") == "全部节点", member
            assert member.get("material_permission") == "write", member
            assert member.get("is_active") is True, member

            with allure.step("从临时项目移除无待办成员"):
                remove_payload = _assert_success(
                    mobile_delivery_client.delete("%s/%s/members/%s" % (PROJECTS_URL, project_id, member_id)),
                    "移动端移除项目成员",
                )
            assert remove_payload.get("data") in (None, {}), remove_payload

            with allure.step("回查节点编辑和成员操作日志"):
                logs_payload = _assert_success(
                    mobile_delivery_client.get(
                        "%s/%s/logs" % (PROJECTS_URL, project_id),
                        params={"page": 1, "page_size": 50},
                    ),
                    "获取移动端项目操作日志",
                )
            logs = _assert_page_payload(logs_payload, "获取移动端项目操作日志", 1, 50)
            actions = {item.get("action") for item in logs["items"]}
            assert {"update_node", "add_member", "update_member", "remove_member"} <= actions, logs
            assert all(item.get("project_id") == project_id for item in logs["items"]), logs

            _close_and_delete_project(mobile_delivery_client, project_id)
            project_id = None
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("资料门禁与验收")
    def test_移动端项目交付_资料门禁提醒确认和验收整改审核(self, mobile_delivery_client):
        _require_write_tests()
        project_id = None
        material_id = None
        version_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "门禁与验收")
            project_id = project["id"]
            node = next(item for item in _get_nodes(mobile_delivery_client, project_id) if item["id"] == project["current_node_id"])
            material_name = "AT-移动端验收资料-%s" % uuid4().hex[:8]

            with allure.step("创建验收门禁所需的临时资料"):
                material_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/materials" % (PROJECTS_URL, project_id),
                        json={
                            "node_id": node["id"],
                            "material_name": material_name,
                            "material_type": "document",
                            "is_required": True,
                            "gate_action": "acceptance_start",
                            "owner_id": mobile_delivery_client.mobile_user_id,
                        },
                    ),
                    "创建移动端验收门禁资料",
                )
            material = material_payload["data"]
            material_id = material.get("id")
            assert isinstance(material_id, int) and material_id > 0, material_payload
            assert material.get("status") == "missing", material

            with allure.step("资料未上传时门禁检查返回具体缺失资料"):
                gate_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/materials/gate-check" % (PROJECTS_URL, project_id),
                        json={"gate_action": "acceptance_start", "node_id": node["id"]},
                    ),
                    "检查移动端验收资料门禁",
                )
            gate = gate_payload["data"]
            assert gate.get("passed") is False, gate
            assert any(item.get("material_id") == material_id for item in gate.get("missing_items") or []), gate

            with allure.step("资料门禁未通过时不允许创建通过状态的验收单"):
                blocked_response = mobile_delivery_client.post(
                    "%s/%s/acceptances" % (PROJECTS_URL, project_id),
                    json={"stage": "initial", "status": "passed", "summary": "不应绕过资料门禁"},
                )
            _assert_error(blocked_response, "资料门禁阻断验收单", GATE_BLOCKED_CODE, "资料门禁未通过")

            with allure.step("对缺失资料发送提醒并在待办列表回查"):
                reminder_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/materials/remind" % (PROJECTS_URL, project_id),
                        json={"material_id": material_id},
                    ),
                    "移动端提醒补齐资料",
                )
            assert reminder_payload.get("data") in (None, {}), reminder_payload
            material_todo = _find_project_todo(mobile_delivery_client, project_id, "material")
            assert material_todo.get("source_id") == material_id, material_todo

            file_name = "AT-移动端验收资料-%s.txt" % uuid4().hex[:8]
            with allure.step("上传、确认资料后复核门禁"):
                uploaded_file = _upload_mobile_delivery_file(mobile_delivery_client, file_name)
                _create_material_version(
                    mobile_delivery_client,
                    project_id,
                    material_id,
                    file_name,
                    "移动端验收资料上传",
                    uploaded_file=uploaded_file,
                )
                versions_payload = _assert_success(
                    mobile_delivery_client.get("%s/%s/materials/%s/versions" % (PROJECTS_URL, project_id, material_id)),
                    "获取移动端验收资料版本",
                )
            versions = (versions_payload["data"] or {}).get("items") or []
            version = next((item for item in versions if item.get("file_name") == file_name), None)
            assert version is not None, versions_payload
            version_id = version.get("id")
            assert isinstance(version_id, int) and version_id > 0, version

            confirm_material_payload = _assert_success(
                mobile_delivery_client.post("%s/%s/materials/%s/confirm" % (PROJECTS_URL, project_id, material_id)),
                "移动端确认验收资料",
            )
            assert confirm_material_payload["data"].get("status") == "confirmed", confirm_material_payload
            passed_gate_payload = _assert_success(
                mobile_delivery_client.post(
                    "%s/%s/materials/gate-check" % (PROJECTS_URL, project_id),
                    json={"gate_action": "acceptance_start", "node_id": node["id"]},
                ),
                "复核移动端验收资料门禁",
            )
            assert passed_gate_payload["data"].get("passed") is True, passed_gate_payload

            with allure.step("验收不通过创建整改项，整改提交后审核通过"):
                acceptance_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/acceptances" % (PROJECTS_URL, project_id),
                        json={
                            "stage": "initial",
                            "status": "failed",
                            "acceptance_user_name": "AT-移动端验收人",
                            "summary": "AT-移动端验收不通过，创建整改项",
                            "rectifications": [{
                                "title": "AT-移动端验收整改-%s" % uuid4().hex[:8],
                                "description": "自动化验收整改问题描述",
                                "severity": "normal",
                                "owner_id": mobile_delivery_client.mobile_user_id,
                                "due_at": (datetime.now() + timedelta(days=2)).replace(microsecond=0).isoformat(),
                            }],
                        },
                    ),
                    "移动端创建不通过验收单",
                )
            acceptance = acceptance_payload["data"]
            assert acceptance.get("status") == "failed", acceptance
            acceptances_payload = _assert_success(
                mobile_delivery_client.get("%s/%s/acceptances" % (PROJECTS_URL, project_id)),
                "获取移动端验收单列表",
            )
            assert any(item.get("id") == acceptance.get("id") for item in (acceptances_payload["data"] or {}).get("items") or []), acceptances_payload
            rectifications_payload = _assert_success(
                mobile_delivery_client.get("%s/%s/rectifications" % (PROJECTS_URL, project_id)),
                "获取移动端验收整改列表",
            )
            rectifications = (rectifications_payload["data"] or {}).get("items") or []
            rectification = next((item for item in rectifications if item.get("acceptance_id") == acceptance.get("id")), None)
            assert rectification is not None, rectifications_payload

            submitted_payload = _assert_success(
                mobile_delivery_client.post(
                    "%s/%s/rectifications/%s/submit" % (PROJECTS_URL, project_id, rectification["id"]),
                    json={"result_desc": "AT-移动端验收整改已完成", "attachments": [], **_mobile_request_meta()},
                ),
                "移动端提交验收整改",
            )
            assert submitted_payload["data"].get("status") == "passed", submitted_payload
            reviewed_payload = _assert_success(
                mobile_delivery_client.post(
                    "%s/%s/rectifications/%s/review" % (PROJECTS_URL, project_id, rectification["id"]),
                    json={"passed": True, "review_opinion": "AT-移动端验收整改审核通过"},
                ),
                "移动端审核验收整改",
            )
            reviewed = reviewed_payload["data"]
            assert reviewed.get("status") == "passed", reviewed
            assert reviewed.get("review_opinion") == "AT-移动端验收整改审核通过", reviewed

            with allure.step("删除资料版本，清理本用例上传的临时文件"):
                delete_version_payload = _assert_success(
                    mobile_delivery_client.delete(
                        "%s/%s/materials/%s/versions/%s" % (PROJECTS_URL, project_id, material_id, version_id)
                    ),
                    "删除移动端验收资料版本",
                )
            assert delete_version_payload["data"].get("id") == material_id, delete_version_payload
            version_id = None

            _close_and_delete_project(mobile_delivery_client, project_id)
            project_id = None
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("节点附件与文件列表")
    def test_移动端项目交付_节点附件资料槽位版本和文件列表(self, mobile_delivery_client):
        _require_write_tests()
        project_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "节点附件")
            project_id = project["id"]
            node = next(item for item in _get_nodes(mobile_delivery_client, project_id) if item["id"] == project["current_node_id"])

            with allure.step("为当前节点创建幂等的附件资料槽位"):
                first_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/nodes/%s/attachment-material" % (PROJECTS_URL, project_id, node["id"])
                    ),
                    "移动端创建节点附件资料槽位",
                )
                second_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/nodes/%s/attachment-material" % (PROJECTS_URL, project_id, node["id"])
                    ),
                    "移动端重复创建节点附件资料槽位",
                )
            attachment_material = first_payload["data"]
            assert isinstance(attachment_material.get("id"), int) and attachment_material["id"] > 0, first_payload
            assert attachment_material.get("node_id") == node["id"], attachment_material
            assert attachment_material.get("material_name") == "节点附件", attachment_material
            assert attachment_material.get("material_type") == "attachment", attachment_material
            assert second_payload["data"].get("id") == attachment_material["id"], second_payload

            with allure.step("按节点加载资料列表，附件槽位应可见"):
                materials_payload = _assert_success(
                    mobile_delivery_client.get(
                        "%s/%s/materials" % (PROJECTS_URL, project_id),
                        params={"node_id": node["id"]},
                    ),
                    "获取移动端节点资料列表",
                )
            materials = (materials_payload["data"] or {}).get("items") or []
            material = next((item for item in materials if item.get("id") == attachment_material["id"]), None)
            assert material is not None, materials_payload
            assert material.get("current_version_id") is None, material

            file_name = "AT-移动端节点附件-%s.txt" % uuid4().hex[:8]
            with allure.step("上传节点附件版本并按文件列表回查"):
                uploaded_file = _upload_mobile_delivery_file(mobile_delivery_client, file_name, folder="project_delivery_attachment")
                _create_material_version(
                    mobile_delivery_client,
                    project_id,
                    attachment_material["id"],
                    file_name,
                    "AT-移动端节点附件版本",
                    uploaded_file=uploaded_file,
                )
                files_payload = _assert_success(
                    mobile_delivery_client.get(
                        "%s/%s/files" % (PROJECTS_URL, project_id),
                        params={"node_id": node["id"], "include_history": True},
                    ),
                    "获取移动端节点附件文件列表",
                )
            files = files_payload["data"]
            assert files.get("node_id") == node["id"], files
            assert files.get("include_history") is True, files
            assert isinstance(files.get("items"), list), files
            assert files.get("total_files", 0) >= 1, files
            matching_group = next(
                (
                    group
                    for group in files["items"]
                    if any(item.get("file_name") == file_name for item in group.get("files") or [])
                ),
                None,
            )
            assert matching_group is not None, files
            assert matching_group.get("node_id") == node["id"], matching_group

            with allure.step("删除节点附件版本，清理本次上传文件"):
                versions_payload = _assert_success(
                    mobile_delivery_client.get(
                        "%s/%s/materials/%s/versions" % (
                            PROJECTS_URL,
                            project_id,
                            attachment_material["id"],
                        )
                    ),
                    "获取移动端节点附件版本",
                )
            versions = (versions_payload["data"] or {}).get("items") or []
            version = next((item for item in versions if item.get("file_name") == file_name), None)
            assert version is not None, versions_payload
            delete_payload = _assert_success(
                mobile_delivery_client.delete(
                    "%s/%s/materials/%s/versions/%s" % (
                        PROJECTS_URL,
                        project_id,
                        attachment_material["id"],
                        version["id"],
                    )
                ),
                "删除移动端节点附件版本",
            )
            assert delete_payload["data"].get("status") == "missing", delete_payload

            _close_and_delete_project(mobile_delivery_client, project_id)
            project_id = None
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("需求确认与待办约束")
    def test_移动端项目交付_需求创建确认删除与待办禁止直接关闭(self, mobile_delivery_client):
        """使用当前登录用户作为协同人，不依赖已移除的需求协同人查询用例。"""
        _require_write_tests()
        project_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "需求确认")
            project_id = project["id"]
            node = next(item for item in _get_nodes(mobile_delivery_client, project_id) if item["id"] == project["current_node_id"])
            title = "AT-移动端现场需求-%s" % uuid4().hex[:8]

            with allure.step("创建关联当前节点的移动端需求"):
                create_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/demands" % (PROJECTS_URL, project_id),
                        json={
                            "source_node_id": node["id"],
                            "collaborator_id": mobile_delivery_client.mobile_user_id,
                            "title": title,
                            "description": "AT-移动端现场登记需求描述不少于五个字符",
                            "source_scene": "现场沟通",
                            "proposer_name": "AT-移动端需求提交人",
                            "impact_scope": "自动化临时项目范围",
                            "expected_date": (date.today() + timedelta(days=5)).isoformat(),
                        },
                    ),
                    "移动端创建项目需求",
                )
            demand = create_payload["data"]
            demand_id = demand.get("id")
            assert isinstance(demand_id, int) and demand_id > 0, create_payload
            assert demand.get("project_id") == project_id, demand
            assert demand.get("source_node_id") == node["id"], demand
            assert demand.get("collaborator_id") == mobile_delivery_client.mobile_user_id, demand
            assert demand.get("status") == "pending_confirm", demand

            with allure.step("待办列表显示需求确认任务，并保留聚合需求待办标识"):
                demand_todo = _find_project_todo(mobile_delivery_client, project_id, "demand")
            assert demand_todo.get("source_id") == demand_id, demand_todo
            assert demand_todo.get("id") == "demand:%s" % demand_id, demand_todo

            # 需求待办是聚合投影，id 为 demand:<source_id>，不能作为整型 path 参数传给
            # 关闭接口。使用项目创建时产生的真实节点待办验证业务层禁止直接关闭的契约。
            node_todo = _find_project_todo(mobile_delivery_client, project_id, "node")
            assert isinstance(node_todo.get("id"), int), node_todo
            direct_close_response = mobile_delivery_client.post(
                "%s/%s/close" % (TODOS_URL, node_todo["id"]),
                json={"remark": "不应直接关闭节点待办"},
            )
            _assert_error(
                direct_close_response,
                "移动端直接关闭节点待办",
                PARAM_ERROR_CODE,
                "待办需进入对应业务处理，不能直接关闭",
            )

            with allure.step("从项目需求列表回查并确认需求"):
                demands_payload = _assert_success(
                    mobile_delivery_client.get("%s/%s/demands" % (PROJECTS_URL, project_id)),
                    "获取移动端项目需求列表",
                )
            demands = (demands_payload["data"] or {}).get("items") or []
            assert any(item.get("id") == demand_id for item in demands), demands_payload
            confirm_payload = _assert_success(
                mobile_delivery_client.post(
                    "%s/%s/demands/%s/confirm" % (PROJECTS_URL, project_id, demand_id),
                    json={
                        "decision": "confirmed",
                        "priority": "high",
                        "external_demand_no": "AT-DEMAND-%s" % uuid4().hex[:8],
                        "confirm_opinion": "AT-移动端需求确认通过",
                    },
                ),
                "移动端确认项目需求",
            )
            confirmed = confirm_payload["data"]
            assert confirmed.get("status") == "confirmed", confirmed
            assert confirmed.get("decision") == "confirmed", confirmed
            assert confirmed.get("priority") == "high", confirmed
            assert confirmed.get("confirm_opinion") == "AT-移动端需求确认通过", confirmed

            with allure.step("删除已确认的临时需求并验证项目中不再存在"):
                delete_payload = _assert_success(
                    mobile_delivery_client.delete("%s/%s/demands/%s" % (PROJECTS_URL, project_id, demand_id)),
                    "移动端删除项目需求",
                )
            assert (delete_payload.get("data") or {}).get("id") == demand_id, delete_payload
            after_delete_payload = _assert_success(
                mobile_delivery_client.get("%s/%s/demands" % (PROJECTS_URL, project_id)),
                "获取删除需求后的项目需求列表",
            )
            assert not any(
                item.get("id") == demand_id
                for item in ((after_delete_payload["data"] or {}).get("items") or [])
            ), after_delete_payload

            _close_and_delete_project(mobile_delivery_client, project_id)
            project_id = None
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("节点资料")
    def test_移动端节点资料_上传版本查看历史并删除(self, mobile_delivery_client):
        _require_write_tests()
        project_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "资料版本")
            project_id = project["id"]
            node = next(item for item in _get_nodes(mobile_delivery_client, project_id) if item["id"] == project["current_node_id"])

            with allure.step("为节点创建移动端上传资料槽位"):
                material_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/materials" % (PROJECTS_URL, project_id),
                        json={
                            "node_id": node["id"],
                            "material_name": "AT-移动端节点资料-%s" % uuid4().hex[:8],
                            "material_type": "attachment",
                            "is_required": False,
                            "owner_id": node.get("owner_id"),
                        },
                    ),
                    "创建移动端节点资料",
                )
            material = material_payload["data"]
            material_id = material.get("id")
            assert isinstance(material_id, int) and material_id > 0, material_payload

            with allure.step("移动端上传资料版本缺少文件名应被拒绝"):
                invalid_version_response = mobile_delivery_client.post(
                    "%s/%s/materials/%s/versions" % (PROJECTS_URL, project_id, material_id),
                    json={"file_size": 12, **_mobile_request_meta()},
                )
            _assert_error_code(invalid_version_response, "移动端上传资料版本缺少文件名", INVALID_PARAMS_CODE)

            file_name = "AT-移动端项目资料-%s.txt" % uuid4().hex[:8]
            with allure.step("上传移动端项目资料文件，并按返回结果创建资料版本"):
                uploaded_file = _upload_mobile_delivery_file(mobile_delivery_client, file_name)
                _create_material_version(
                    mobile_delivery_client,
                    project_id,
                    material_id,
                    file_name,
                    "移动端节点资料上传",
                    uploaded_file=uploaded_file,
                )

            with allure.step("加载节点资料版本历史"):
                versions_payload = _assert_success(
                    mobile_delivery_client.get("%s/%s/materials/%s/versions" % (PROJECTS_URL, project_id, material_id)),
                    "获取移动端节点资料版本",
                )
            versions = (versions_payload["data"] or {}).get("items") or []
            version = next((item for item in versions if item.get("file_name") == file_name), None)
            assert version is not None, "移动端资料版本列表未包含上传文件：%s" % versions_payload
            version_id = version.get("id")
            assert isinstance(version_id, int) and version_id > 0, version

            with allure.step("从移动端节点资料列表删除该版本"):
                delete_payload = _assert_success(
                    mobile_delivery_client.delete(
                        "%s/%s/materials/%s/versions/%s" % (PROJECTS_URL, project_id, material_id, version_id)
                    ),
                    "删除移动端节点资料版本",
                )
            assert delete_payload["data"].get("id") == material_id, delete_payload

            _close_and_delete_project(mobile_delivery_client, project_id)
            project_id = None
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("整改提交")
    def test_移动端整改_提交说明附件并同步关闭待办(self, mobile_delivery_client):
        _require_write_tests()
        project_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "整改")
            project_id = project["id"]
            owner_id = project.get("project_manager_id")
            assert isinstance(owner_id, int) and owner_id > 0, "项目缺少负责人：%s" % project
            rectification_name = "AT-移动端整改-%s" % uuid4().hex[:8]

            with allure.step("准备移动端整改待办"):
                create_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/rectifications" % (PROJECTS_URL, project_id),
                        json={
                            "title": rectification_name,
                            "description": "移动端整改提交接口自动化问题描述",
                            "severity": "normal",
                            "owner_id": owner_id,
                            "due_at": (datetime.now() + timedelta(days=2)).isoformat(),
                        },
                    ),
                    "创建移动端整改待办",
                )
            rectification = create_payload["data"]
            rectification_id = rectification.get("id")
            assert isinstance(rectification_id, int) and rectification_id > 0, create_payload
            _find_project_todo(mobile_delivery_client, project_id, "rectification")

            with allure.step("移动端提交整改时缺少整改说明应被拒绝"):
                invalid_submit_response = mobile_delivery_client.post(
                    "%s/%s/rectifications/%s/submit" % (PROJECTS_URL, project_id, rectification_id),
                    json={"result_desc": "", "attachments": [], **_mobile_request_meta()},
                )
            _assert_error_code(invalid_submit_response, "移动端提交整改缺少说明", INVALID_PARAMS_CODE)

            attachment = {
                "attachment_id": "https://example.com/at-mobile-rectification.jpg",
                "file_name": "AT-移动端整改照片.jpg",
                "file_size": 12,
                "download_url": "https://example.com/at-mobile-rectification.jpg",
                "mime_type": "image/jpeg",
                "source_client": "mobile",
            }
            with allure.step("提交移动端整改说明和附件"):
                submit_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/rectifications/%s/submit" % (PROJECTS_URL, project_id, rectification_id),
                        json={
                            "result_desc": "移动端已完成整改并提交照片佐证",
                            "attachments": [attachment],
                            **_mobile_request_meta(),
                        },
                    ),
                    "移动端提交整改",
                )
            submitted = submit_payload["data"]
            assert submitted.get("status") == "passed", submitted
            assert submitted.get("result_desc") == "移动端已完成整改并提交照片佐证", submitted
            assert len(submitted.get("attachments") or []) == 1, submitted

            with allure.step("整改提交后移动端整改待办应关闭"):
                todos = _list_todos(mobile_delivery_client, todo_type="rectification")
            assert not any(todo.get("source_id") == rectification_id for todo in todos["items"]), todos

            _close_and_delete_project(mobile_delivery_client, project_id)
            project_id = None
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)

    @allure.feature("节点验收确认")
    def test_移动端节点确认_驳回后重新提交并确认通过(self, mobile_delivery_client):
        _require_write_tests()
        project_id = None
        try:
            project = _create_temporary_project(mobile_delivery_client, "节点确认")
            project_id = project["id"]
            submitted = _prepare_submitted_confirm_node(mobile_delivery_client, project_id)
            node_id = submitted["id"]

            with allure.step("确认页加载验收确认待办"):
                confirm_todo = _find_project_todo(mobile_delivery_client, project_id, "confirm")
            assert confirm_todo.get("source_id") == node_id, confirm_todo

            with allure.step("从移动端确认页提交驳回原因"):
                reject_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/nodes/%s/reject" % (PROJECTS_URL, project_id, node_id),
                        json={
                            "reject_reason": "移动端自动化验证驳回后重新处理",
                            "client_version": submitted["version"],
                            **_mobile_request_meta(),
                        },
                    ),
                    "移动端驳回节点",
                )
            rejected = reject_payload["data"]
            assert rejected.get("status") == "rejected", rejected
            assert rejected.get("reject_reason") == "移动端自动化验证驳回后重新处理", rejected
            _find_project_todo(mobile_delivery_client, project_id, "node")

            with allure.step("准备重新提交状态并刷新移动端确认待办"):
                resubmit_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/nodes/%s/submit" % (PROJECTS_URL, project_id, node_id),
                        json={
                            "result": "completed",
                            "remark": "自动化重新提交供移动端确认",
                            "client_version": rejected["version"],
                        },
                    ),
                    "重新提交节点",
                )
            resubmitted = resubmit_payload["data"]
            assert resubmitted.get("status") == "submitted", resubmitted
            _find_project_todo(mobile_delivery_client, project_id, "confirm")

            with allure.step("从移动端确认页确认节点通过"):
                confirm_payload = _assert_success(
                    mobile_delivery_client.post(
                        "%s/%s/nodes/%s/confirm" % (PROJECTS_URL, project_id, node_id),
                        json={
                            "remark": "移动端自动化确认通过",
                            "client_version": resubmitted["version"],
                            **_mobile_request_meta(),
                        },
                    ),
                    "移动端确认节点",
            )
            confirmed = confirm_payload["data"]
            assert confirmed.get("status") == "confirmed", confirmed
            # 确认备注写入操作日志，节点 remark 保留最近一次提交时的处理说明。
            assert confirmed.get("remark") == "自动化重新提交供移动端确认", confirmed
            confirmed_detail = _get_node_detail(mobile_delivery_client, project_id, node_id)
            assert any(
                log.get("remark") == "移动端自动化确认通过"
                for log in confirmed_detail["logs"]
            ), "移动端确认备注未写入节点操作日志：%s" % confirmed_detail["logs"]

            _close_and_delete_project(mobile_delivery_client, project_id)
            project_id = None
        finally:
            _cleanup_project_quietly(mobile_delivery_client, project_id)
