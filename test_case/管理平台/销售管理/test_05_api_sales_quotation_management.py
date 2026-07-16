# -*- coding: utf-8 -*-
"""管理平台销售管理-报价单接口自动化测试。

该模块使用重写后的 ``/v1/sales/quotations`` 工作台接口。测试统一读取
``MANAGEMENT_TEST_ACCOUNT`` 登录；写入链路创建 ``AT-`` 前缀的客户、销售商品
和报价单，并在 finally 中清理报价单、商品和客户。预览/正式导出是报价单正式
功能，会产生报价单导出记录及 xlsx 文件。
"""
from datetime import date
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, MANAGEMENT_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
CUSTOMERS_URL = "/v1/customers"
SALES_PRODUCTS_URL = "/v1/sales/products"
SALES_CUSTOMER_OPTIONS_URL = "/v1/sales/customers/options"
SALES_QUOTATIONS_URL = "/v1/sales/quotations"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
PARAM_ERROR_CODE = 4100
TOKEN_INVALID_CODE = 5104
NOT_FOUND_CODE = 4040
OPERATION_NOT_ALLOWED_CODE = 5004
QUOTE_NOT_FOUND_CODE = 5600
QUOTE_ITEM_INVALID_CODE = 5603
PRODUCT_DISABLED_CODE = 5604

QUOTE_STATUSES = {"draft", "pending_review", "confirmed", "voided"}
QUOTE_TEMPLATE_PROJECT_OVERVIEW = "project_overview"
PRODUCT_REQUIRED_FIELDS = {"id", "name", "product_code", "category", "unit", "default_price", "status"}


def _require_write_tests():
    """关闭全局写操作开关时跳过会创建报价数据的用例。"""
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _parse_json(response, action):
    """解析 JSON，并在失败时输出足够的请求定位信息。"""
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
    """校验统一成功响应，并明确标记销售报价权限不足。"""
    assert response.status_code == 200, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = _parse_json(response, action)
    if payload.get("code") == 4030:
        pytest.skip("登录账号缺少销售报价单管理权限")
    assert payload.get("code") == SUCCESS_CODE, "%s 业务失败：%s" % (action, payload)
    assert "data" in payload, "%s 成功响应缺少 data：%s" % (action, payload)
    return payload


def _assert_error_code(response, action, expected_code, expected_http_status=200):
    """校验业务错误响应。"""
    assert response.status_code == expected_http_status, "%s HTTP 状态异常：%s" % (action, response.text)
    payload = _parse_json(response, action)
    assert payload.get("code") == expected_code, "%s 错误码不正确：%s" % (action, payload)
    return payload


def _assert_page_payload(payload, action, expected_page=None, expected_page_size=None):
    """校验报价单、客户选项和导出记录的分页响应。"""
    data = payload["data"]
    assert isinstance(data, dict), "%s data 应为分页对象：%s" % (action, payload)
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


def _assert_workspace_shape(workspace, action, expected_quote_id=None):
    """校验创建、保存和状态流转后返回的报价工作台核心结构。"""
    assert isinstance(workspace, dict), "%s 报价工作台应为对象：%r" % (action, workspace)
    required_fields = {
        "id",
        "quote_no",
        "status",
        "template_type",
        "customer_snapshot",
        "main",
        "quote_groups",
        "items",
        "summary",
        "available_actions",
        "version",
    }
    missing_fields = required_fields - set(workspace)
    assert not missing_fields, "%s 工作台缺少字段：%s；实际=%s" % (action, missing_fields, workspace)
    assert isinstance(workspace["id"], int) and workspace["id"] > 0, "%s 报价单 id 非法：%s" % (action, workspace)
    assert isinstance(workspace["quote_no"], str) and workspace["quote_no"], "%s 报价单号为空：%s" % (action, workspace)
    assert workspace["status"] in QUOTE_STATUSES, "%s 报价状态不合法：%s" % (action, workspace)
    assert workspace["template_type"] == QUOTE_TEMPLATE_PROJECT_OVERVIEW, "%s 模板类型异常：%s" % (action, workspace)
    assert isinstance(workspace["customer_snapshot"], dict), "%s 客户快照应为对象：%s" % (action, workspace)
    assert isinstance(workspace["quote_groups"], list), "%s 报价分组应为数组：%s" % (action, workspace)
    assert isinstance(workspace["items"], list), "%s 报价明细应为数组：%s" % (action, workspace)
    assert isinstance(workspace["summary"], dict), "%s 金额汇总应为对象：%s" % (action, workspace)
    assert isinstance(workspace["available_actions"], list), "%s 可操作项应为数组：%s" % (action, workspace)
    assert isinstance(workspace["version"], int) and workspace["version"] >= 1, "%s 版本号非法：%s" % (action, workspace)
    if expected_quote_id is not None:
        assert workspace["id"] == expected_quote_id, "%s 报价单 id 不正确：%s" % (action, workspace)


def _login_client(username, password, action):
    """使用唯一管理平台测试账号登录。"""
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
def sales_quotation_client():
    """所有报价单用例共用 MANAGEMENT_TEST_ACCOUNT 的登录态。"""
    account = MANAGEMENT_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录管理平台")

    with allure.step("登录管理平台并获取销售报价单 Token"):
        client = _login_client(username, password, "登录销售报价单管理账号")
    yield client
    client.headers.pop("Authorization", None)


def _customer_body(name=None):
    """构造报价单测试所需的临时客户。"""
    return {
        "name": name or "AT-报价客户-%s" % uuid4().hex[:12],
        "deployment_type": "public_cloud",
        "customer_type": "school",
        "manager_name": "接口自动化报价客户联系人",
        "manager_phone": "13900000000",
        "service_period": 12,
        "remarks": "报价单接口自动化临时客户",
        "call_domain_api": False,
    }


def _create_temporary_customer(client):
    """创建报价单客户快照来源。"""
    body = _customer_body()
    payload = _assert_success(client.post(CUSTOMERS_URL, json=body), "创建报价临时客户")
    customer = payload["data"]
    assert isinstance(customer.get("id"), int) and customer["id"] > 0, "临时客户 id 非法：%s" % customer
    assert customer.get("name") == body["name"], customer
    return customer


def _cleanup_temporary_customer(client, customer_id):
    """通过客户业务删除接口软删除临时客户。"""
    if not customer_id:
        return
    try:
        client.delete("%s/%s" % (CUSTOMERS_URL, customer_id))
    except Exception:
        pass


def _product_body(name=None, status="enabled"):
    """构造报价单软件分组可用的临时销售商品。"""
    return {
        "name": name or "AT-报价商品-%s" % uuid4().hex[:12],
        "category": "software",
        "quote_group_type": "software",
        "spec_name": "报价标准版-%s" % uuid4().hex[:8],
        "unit": "套",
        "usage_scene": "报价单接口自动化",
        "default_price": "1000.00",
        "guide_price": "1200.00",
        "tax_rate": "6.00",
        "cost_price": "800.00",
        "default_remark": "报价单接口自动化临时商品",
        "status": status,
        "sort_order": 99,
        "images": [],
    }


def _create_temporary_product(client, status="enabled"):
    """创建临时销售商品。"""
    body = _product_body(status=status)
    payload = _assert_success(client.post(SALES_PRODUCTS_URL, json=body), "创建报价临时销售商品")
    product = payload["data"]
    missing_fields = PRODUCT_REQUIRED_FIELDS - set(product)
    assert not missing_fields, "临时销售商品缺少字段：%s；实际=%s" % (missing_fields, product)
    assert isinstance(product.get("id"), int) and product["id"] > 0, product
    assert product.get("status") == status, product
    return product


def _cleanup_temporary_product(client, product_id):
    """临时商品按停用后删除的规则清理。"""
    if not product_id:
        return
    try:
        client.post("%s/%s/disable" % (SALES_PRODUCTS_URL, product_id))
        client.delete("%s/%s" % (SALES_PRODUCTS_URL, product_id))
    except Exception:
        pass


def _quote_body(customer_id, title=None):
    """构造满足报价单草稿必填字段的创建请求。"""
    return {
        "customer_id": customer_id,
        "template_type": QUOTE_TEMPLATE_PROJECT_OVERVIEW,
        "quote_title": title or "AT-报价单-%s" % uuid4().hex[:12],
        "quote_date": date.today().isoformat(),
        "valid_days": 30,
        "service_years": "1",
        "canteen_count": 1,
        "payment_terms": "合同签订后支付",
        "delivery_terms": "接口自动化交付条款",
        "remark_terms": "接口自动化报价单临时数据",
    }


def _create_temporary_quote(client, customer_id):
    """创建草稿报价单并校验默认软件/硬件/服务/实施分组。"""
    body = _quote_body(customer_id)
    payload = _assert_success(client.post(SALES_QUOTATIONS_URL, json=body), "创建报价单草稿")
    workspace = payload["data"]
    _assert_workspace_shape(workspace, "创建报价单草稿")
    assert workspace["status"] == "draft", workspace
    assert workspace["customer_snapshot"].get("customer_id") == customer_id, workspace
    group_codes = {item.get("group_code") for item in workspace["quote_groups"]}
    assert {"software", "hardware", "service_resource", "implementation"} <= group_codes, workspace
    return workspace


def _save_workspace_with_product(client, quote, product, title_suffix="已保存"):
    """保存一条软件商品明细，并返回最新版本的报价工作台。"""
    title = "AT-报价单%s-%s" % (title_suffix, uuid4().hex[:10])
    payload = _assert_success(
        client.put(
            "%s/%s" % (SALES_QUOTATIONS_URL, quote["id"]),
            json={
                "client_version": quote["version"],
                "main": {
                    "quote_title": title,
                    "payment_terms": "保存工作台后的付款条款",
                    "delivery_terms": "保存工作台后的交付条款",
                    "remark_terms": "保存工作台后的自动化备注",
                },
                "quote_groups": [
                    {
                        "group_code": "software",
                        "group_name": "软件平台",
                        "group_type": "software",
                        "sort_order": 1,
                    }
                ],
                "items": [
                    {
                        "group_code": "software",
                        "product_id": product["id"],
                        "quantity": "2",
                        "unit_price": "1000.00",
                        "discount_rate": "100.00",
                        "tax_rate": "6.00",
                        "remark": "报价单自动化软件明细",
                        "sort_order": 1,
                    }
                ],
            },
        ),
        "保存报价工作台",
    )
    workspace = payload["data"]
    _assert_workspace_shape(workspace, "保存报价工作台", expected_quote_id=quote["id"])
    assert workspace["status"] == "draft", workspace
    assert workspace["main"].get("quote_title") == title, workspace
    assert len(workspace["quote_groups"]) == 1 and workspace["quote_groups"][0].get("group_code") == "software", workspace
    assert len(workspace["items"]) == 1 and workspace["items"][0].get("product_id") == product["id"], workspace
    assert float(workspace["summary"].get("subtotal_amount")) == 2000.0, workspace
    assert float(workspace["summary"].get("tax_amount")) == 120.0, workspace
    assert float(workspace["summary"].get("total_amount")) == 2120.0, workspace
    return workspace


def _cleanup_temporary_quote(client, quote_id):
    """作废并删除临时报价单；已确认报价单必须先作废才能删除。"""
    if not quote_id:
        return
    try:
        client.post(
            "%s/%s/void" % (SALES_QUOTATIONS_URL, quote_id),
            json={"reason": "接口自动化清理临时报价单"},
        )
        client.delete("%s/%s" % (SALES_QUOTATIONS_URL, quote_id))
    except Exception:
        pass


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-报价单")
class Test销售报价单查询与校验:
    """鉴权、列表、客户选项和不产生业务数据的边界校验。"""

    @allure.feature("访问权限")
    def test_未登录访问报价单列表_返回令牌无效(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Authorization 请求报价单列表"):
            response = anonymous_client.get(SALES_QUOTATIONS_URL)
        _assert_error_code(response, "未登录获取报价单列表", TOKEN_INVALID_CODE)

    @allure.feature("查询与客户选项")
    def test_报价单列表与客户选项_分页结构完整(self, sales_quotation_client):
        with allure.step("查询默认报价单列表"):
            quotation_payload = _assert_success(
                sales_quotation_client.get(SALES_QUOTATIONS_URL, params={"page": 1, "page_size": 10}),
                "获取报价单列表",
            )
        _assert_page_payload(quotation_payload, "获取报价单列表", expected_page=1, expected_page_size=10)

        with allure.step("查询报价单可选客户"):
            customer_payload = _assert_success(
                sales_quotation_client.get(SALES_CUSTOMER_OPTIONS_URL, params={"page": 1, "page_size": 10}),
                "获取报价单客户选项",
            )
        customer_data = _assert_page_payload(customer_payload, "获取报价单客户选项", expected_page=1, expected_page_size=10)
        for item in customer_data["items"]:
            assert isinstance(item.get("id"), int) and item.get("customer_name"), item

    @allure.feature("参数校验")
    def test_报价单创建_必填字段非法分页和不存在详情校验(self, sales_quotation_client):
        with allure.step("使用空请求体创建报价单"):
            empty_create_response = sales_quotation_client.post(SALES_QUOTATIONS_URL, json={})
        _assert_error_code(empty_create_response, "创建报价单缺少必填字段", PARAM_ERROR_CODE)

        with allure.step("使用非法页码查询报价单列表"):
            invalid_page_response = sales_quotation_client.get(SALES_QUOTATIONS_URL, params={"page": 0, "page_size": 10})
        _assert_error_code(invalid_page_response, "报价单列表非法页码", INVALID_PARAMS_CODE)

        with allure.step("查询不存在的报价单详情"):
            detail_response = sales_quotation_client.get("%s/%s" % (SALES_QUOTATIONS_URL, 2147483647))
        _assert_error_code(detail_response, "查询不存在的报价单详情", QUOTE_NOT_FOUND_CODE)

    @allure.feature("兼容接口")
    def test_报价单不支持的PDF与分享接口_返回业务限制(self, sales_quotation_client):
        with allure.step("调用当前版本不支持的 PDF 导出接口"):
            pdf_response = sales_quotation_client.post("%s/%s/export/pdf" % (SALES_QUOTATIONS_URL, 2147483647), json={})
        _assert_error_code(pdf_response, "报价单 PDF 导出", OPERATION_NOT_ALLOWED_CODE)

        with allure.step("调用当前版本不支持的分享接口"):
            share_response = sales_quotation_client.post("%s/%s/share" % (SALES_QUOTATIONS_URL, 2147483647), json={})
        _assert_error_code(share_response, "创建报价单分享链接", OPERATION_NOT_ALLOWED_CODE)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-报价单")
class Test销售报价单业务链路:
    """草稿、明细、导出、审核、确认、作废、复制和删除完整业务链路。"""

    @allure.feature("草稿工作台")
    def test_报价单草稿_保存明细复制预览导出与删除(self, sales_quotation_client):
        _require_write_tests()
        customer_id = None
        product_id = None
        quote_id = None
        copied_quote_id = None
        try:
            customer = _create_temporary_customer(sales_quotation_client)
            customer_id = customer["id"]
            product = _create_temporary_product(sales_quotation_client)
            product_id = product["id"]
            quote = _create_temporary_quote(sales_quotation_client, customer_id)
            quote_id = quote["id"]
            workspace = _save_workspace_with_product(sales_quotation_client, quote, product)

            with allure.step("按标题、草稿状态和客户筛选报价单"):
                list_payload = _assert_success(
                    sales_quotation_client.get(
                        SALES_QUOTATIONS_URL,
                        params={
                            "keyword": workspace["main"]["quote_title"],
                            "status": "draft",
                            "customer_id": customer_id,
                            "page": 1,
                            "page_size": 10,
                        },
                    ),
                    "筛选报价单草稿",
                )
            list_data = _assert_page_payload(list_payload, "筛选报价单草稿", expected_page=1, expected_page_size=10)
            assert any(item.get("id") == quote_id for item in list_data["items"]), list_data

            with allure.step("复制已保存的报价草稿"):
                copy_payload = _assert_success(
                    sales_quotation_client.post("%s/%s/copy" % (SALES_QUOTATIONS_URL, quote_id), json={}),
                    "复制报价单",
                )
            copied_workspace = copy_payload["data"]
            _assert_workspace_shape(copied_workspace, "复制报价单")
            copied_quote_id = copied_workspace["id"]
            assert copied_quote_id != quote_id and copied_workspace["status"] == "draft", copied_workspace
            assert len(copied_workspace["items"]) == 1, copied_workspace

            with allure.step("草稿报价单预览导出 xlsx"):
                preview_payload = _assert_success(
                    sales_quotation_client.post("%s/%s/preview-export" % (SALES_QUOTATIONS_URL, quote_id), json={}),
                    "预览导出报价单",
                )
            preview = preview_payload["data"]
            assert isinstance(preview.get("download_url"), str) and preview["download_url"], preview
            assert isinstance(preview.get("file_name"), str) and preview["file_name"].endswith(".xlsx"), preview
            assert isinstance(preview.get("file_size"), int) and preview["file_size"] > 0, preview
            assert (preview.get("export_record") or {}).get("export_type") == "preview", preview

            with allure.step("查询报价单详情和预览导出记录"):
                detail_payload = _assert_success(
                    sales_quotation_client.get("%s/%s" % (SALES_QUOTATIONS_URL, quote_id)),
                    "获取保存后报价单详情",
                )
                records_payload = _assert_success(
                    sales_quotation_client.get(
                        "%s/%s/export-records" % (SALES_QUOTATIONS_URL, quote_id),
                        params={"page": 1, "page_size": 10},
                    ),
                    "获取报价单导出记录",
                )
            detail = detail_payload["data"]
            _assert_workspace_shape(detail, "获取保存后报价单详情", expected_quote_id=quote_id)
            records_data = _assert_page_payload(records_payload, "获取报价单导出记录", expected_page=1, expected_page_size=10)
            assert any(item.get("export_type") == "preview" for item in records_data["items"]), records_data

            with allure.step("删除报价单副本和原始草稿"):
                copied_delete_payload = _assert_success(
                    sales_quotation_client.delete("%s/%s" % (SALES_QUOTATIONS_URL, copied_quote_id)),
                    "删除报价单副本",
                )
                original_delete_payload = _assert_success(
                    sales_quotation_client.delete("%s/%s" % (SALES_QUOTATIONS_URL, quote_id)),
                    "删除报价单草稿",
                )
            assert copied_delete_payload["data"].get("deleted") is True, copied_delete_payload
            assert original_delete_payload["data"].get("deleted") is True, original_delete_payload
            copied_quote_id = None
            quote_id = None
        finally:
            _cleanup_temporary_quote(sales_quotation_client, copied_quote_id)
            _cleanup_temporary_quote(sales_quotation_client, quote_id)
            _cleanup_temporary_product(sales_quotation_client, product_id)
            _cleanup_temporary_customer(sales_quotation_client, customer_id)

    @allure.feature("审核确认与导出")
    def test_报价单审核_退回确认正式导出作废与删除约束(self, sales_quotation_client):
        _require_write_tests()
        customer_id = None
        product_id = None
        quote_id = None
        try:
            customer = _create_temporary_customer(sales_quotation_client)
            customer_id = customer["id"]
            product = _create_temporary_product(sales_quotation_client)
            product_id = product["id"]
            quote = _create_temporary_quote(sales_quotation_client, customer_id)
            quote_id = quote["id"]
            workspace = _save_workspace_with_product(sales_quotation_client, quote, product, title_suffix="审核链路")

            with allure.step("提交草稿报价单审核"):
                submitted_payload = _assert_success(
                    sales_quotation_client.post("%s/%s/submit-review" % (SALES_QUOTATIONS_URL, quote_id), json={}),
                    "提交报价单审核",
                )
            submitted = submitted_payload["data"]
            _assert_workspace_shape(submitted, "提交报价单审核", expected_quote_id=quote_id)
            assert submitted["status"] == "pending_review", submitted

            with allure.step("退回待审核报价单到草稿"):
                rejected_payload = _assert_success(
                    sales_quotation_client.post(
                        "%s/%s/reject" % (SALES_QUOTATIONS_URL, quote_id),
                        json={"reason": "接口自动化验证退回原因"},
                    ),
                    "退回报价单审核",
                )
            rejected = rejected_payload["data"]
            assert rejected["status"] == "draft", rejected
            assert rejected["main"].get("reject_reason") == "接口自动化验证退回原因", rejected

            with allure.step("重新提交并确认报价单"):
                resubmitted_payload = _assert_success(
                    sales_quotation_client.post("%s/%s/submit-review" % (SALES_QUOTATIONS_URL, quote_id), json={}),
                    "重新提交报价单审核",
                )
                confirmed_payload = _assert_success(
                    sales_quotation_client.post("%s/%s/confirm" % (SALES_QUOTATIONS_URL, quote_id), json={}),
                    "确认报价单",
                )
            assert resubmitted_payload["data"].get("status") == "pending_review", resubmitted_payload
            confirmed = confirmed_payload["data"]
            assert confirmed.get("status") == "confirmed", confirmed
            assert "official_export" in confirmed.get("available_actions", []), confirmed

            with allure.step("已确认报价单直接删除应被拒绝"):
                delete_confirmed_response = sales_quotation_client.delete("%s/%s" % (SALES_QUOTATIONS_URL, quote_id))
            _assert_error_code(delete_confirmed_response, "删除已确认报价单", OPERATION_NOT_ALLOWED_CODE)

            with allure.step("已确认报价单正式导出 xlsx"):
                official_payload = _assert_success(
                    sales_quotation_client.post("%s/%s/official-export" % (SALES_QUOTATIONS_URL, quote_id), json={}),
                    "正式导出报价单",
                )
            official = official_payload["data"]
            assert isinstance(official.get("download_url"), str) and official["download_url"], official
            assert (official.get("export_record") or {}).get("export_type") == "official", official

            with allure.step("校验预览外的正式导出记录与计数"):
                records_payload = _assert_success(
                    sales_quotation_client.get(
                        "%s/%s/export-records" % (SALES_QUOTATIONS_URL, quote_id),
                        params={"page": 1, "page_size": 10},
                    ),
                    "获取正式导出记录",
                )
                detail_payload = _assert_success(
                    sales_quotation_client.get("%s/%s" % (SALES_QUOTATIONS_URL, quote_id)),
                    "获取已确认报价单详情",
                )
            records_data = _assert_page_payload(records_payload, "获取正式导出记录", expected_page=1, expected_page_size=10)
            assert any(item.get("export_type") == "official" for item in records_data["items"]), records_data
            assert detail_payload["data"].get("official_export_count", 0) >= 1, detail_payload

            with allure.step("作废已确认报价单后删除"):
                void_payload = _assert_success(
                    sales_quotation_client.post(
                        "%s/%s/void" % (SALES_QUOTATIONS_URL, quote_id),
                        json={"reason": "接口自动化验证作废原因"},
                    ),
                    "作废已确认报价单",
                )
                delete_payload = _assert_success(
                    sales_quotation_client.delete("%s/%s" % (SALES_QUOTATIONS_URL, quote_id)),
                    "删除已作废报价单",
                )
            assert void_payload["data"].get("status") == "voided", void_payload
            assert delete_payload["data"].get("deleted") is True, delete_payload
            quote_id = None
        finally:
            _cleanup_temporary_quote(sales_quotation_client, quote_id)
            _cleanup_temporary_product(sales_quotation_client, product_id)
            _cleanup_temporary_customer(sales_quotation_client, customer_id)

    @allure.feature("明细商品约束")
    def test_报价单明细_停用销售商品不可写入工作台(self, sales_quotation_client):
        _require_write_tests()
        customer_id = None
        product_id = None
        quote_id = None
        try:
            customer = _create_temporary_customer(sales_quotation_client)
            customer_id = customer["id"]
            product = _create_temporary_product(sales_quotation_client, status="disabled")
            product_id = product["id"]
            quote = _create_temporary_quote(sales_quotation_client, customer_id)
            quote_id = quote["id"]

            with allure.step("使用停用商品保存报价工作台明细"):
                response = sales_quotation_client.put(
                    "%s/%s" % (SALES_QUOTATIONS_URL, quote_id),
                    json={
                        "client_version": quote["version"],
                        "quote_groups": [
                            {
                                "group_code": "software",
                                "group_name": "软件平台",
                                "group_type": "software",
                                "sort_order": 1,
                            }
                        ],
                        "items": [
                            {
                                "group_code": "software",
                                "product_id": product_id,
                                "quantity": "1",
                                "unit_price": "1000.00",
                                "discount_rate": "100.00",
                                "tax_rate": "6.00",
                                "sort_order": 1,
                            }
                        ],
                    },
                )
            _assert_error_code(response, "使用停用商品保存报价明细", PRODUCT_DISABLED_CODE)
        finally:
            _cleanup_temporary_quote(sales_quotation_client, quote_id)
            _cleanup_temporary_product(sales_quotation_client, product_id)
            _cleanup_temporary_customer(sales_quotation_client, customer_id)
