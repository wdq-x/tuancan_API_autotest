# -*- coding: utf-8 -*-
"""管理平台销售管理-销售商品接口自动化测试。

被测接口使用重写后的 ``/v1/sales/products`` 路径。测试账号、环境地址和
写操作开关统一读取 ``config/project_information.py`` 中的配置；新增商品使用
``AT-`` 前缀，测试结束时按照“停用后删除”的业务规则清理。
"""
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, MANAGEMENT_TEST_ACCOUNT, default_headers
from utils.http_client import HttpClient


LOGIN_URL = "/v1/login"
SALES_PRODUCTS_URL = "/v1/sales/products"
SALES_PRODUCT_OPTIONS_URL = "/v1/sales/products/options"
SALES_PRODUCT_NEXT_CODE_URL = "/v1/sales/products/next-code"
SALES_PRODUCT_IMPORT_URL = "/v1/sales-products/import"

SUCCESS_CODE = 20000
INVALID_PARAMS_CODE = 4001
TOKEN_INVALID_CODE = 5104
FORBIDDEN_CODE = 4030
NOT_FOUND_CODE = 4040
NAME_ALREADY_EXISTS_CODE = 5001
OPERATION_NOT_ALLOWED_CODE = 5004

PRODUCT_CATEGORIES = {"software", "hardware", "service_resource", "service", "implementation"}
PRODUCT_STATUSES = {"enabled", "disabled"}
PRODUCT_REQUIRED_FIELDS = {
    "id",
    "product_code",
    "name",
    "category",
    "quote_group_type",
    "unit",
    "default_price",
    "effective_price",
    "status",
    "images",
    "created_by",
}


def _require_write_tests():
    """关闭全局写操作开关时，跳过会创建销售商品的用例。"""
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _parse_json(response, action):
    """解析响应，失败信息中附带 URL、状态码和响应片段。"""
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
    """校验统一成功响应，缺少销售商品权限时明确跳过。"""
    assert response.status_code == 200, (
        "%s HTTP 状态异常。url=%s, status=%s, body=%s"
        % (action, response.url, response.status_code, response.text[:500])
    )
    payload = _parse_json(response, action)
    if payload.get("code") == FORBIDDEN_CODE:
        pytest.skip("登录账号缺少销售商品管理权限")
    assert payload.get("code") == SUCCESS_CODE, "%s 业务失败：%s" % (action, payload)
    assert "data" in payload, "%s 成功响应缺少 data：%s" % (action, payload)
    return payload


def _assert_error_code(response, action, expected_code, expected_http_status=200):
    """校验统一业务错误码。"""
    assert response.status_code == expected_http_status, "%s HTTP 状态异常：%s" % (action, response.text)
    payload = _parse_json(response, action)
    assert payload.get("code") == expected_code, "%s 错误码不正确：%s" % (action, payload)
    return payload


def _assert_page_payload(payload, action, expected_page=None, expected_page_size=None):
    """校验商品列表和商品选项共用的分页结构。"""
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


def _assert_product_shape(product, action, expected_product_id=None):
    """校验创建、详情、更新和状态接口的商品核心字段。"""
    assert isinstance(product, dict), "%s 商品应为对象，实际为 %r" % (action, product)
    missing_fields = PRODUCT_REQUIRED_FIELDS - set(product)
    assert not missing_fields, "%s 商品缺少字段：%s；实际=%s" % (action, missing_fields, product)
    assert isinstance(product["id"], int) and product["id"] > 0, "%s 商品 id 非法：%s" % (action, product)
    assert isinstance(product["product_code"], str) and product["product_code"], "%s 商品编码为空：%s" % (action, product)
    assert isinstance(product["name"], str) and product["name"].strip(), "%s 商品名称为空：%s" % (action, product)
    assert product["category"] in PRODUCT_CATEGORIES, "%s 商品类别不合法：%s" % (action, product)
    assert product["quote_group_type"] in PRODUCT_CATEGORIES, "%s 报价分组类别不合法：%s" % (action, product)
    assert isinstance(product["unit"], str) and product["unit"], "%s 商品单位为空：%s" % (action, product)
    assert product["status"] in PRODUCT_STATUSES, "%s 商品状态不合法：%s" % (action, product)
    assert isinstance(product["images"], list), "%s 商品图片应为数组：%s" % (action, product)
    assert product["created_by"] is not None, "%s 创建人不能为空：%s" % (action, product)
    if expected_product_id is not None:
        assert product["id"] == expected_product_id, "%s 商品 id 不正确：%s" % (action, product)


def _login_client(username, password, action):
    """登录唯一管理平台测试账号并写入 Bearer Token。"""
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
def sales_product_client():
    """所有销售商品用例都使用 MANAGEMENT_TEST_ACCOUNT 登录。"""
    account = MANAGEMENT_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("未配置 MANAGEMENT_TEST_ACCOUNT，无法登录管理平台")

    with allure.step("登录管理平台并获取销售商品 Token"):
        client = _login_client(username, password, "登录销售商品管理账号")
    yield client
    client.headers.pop("Authorization", None)


def _product_body(name=None, spec_name=None, **overrides):
    """构造合法软件类临时销售商品请求体。"""
    body = {
        "name": name or "AT-销售商品-%s" % uuid4().hex[:12],
        "category": "software",
        "quote_group_type": "software",
        "spec_name": spec_name or "标准版-%s" % uuid4().hex[:8],
        "unit": "套",
        "usage_scene": "接口自动化验证",
        "default_price": "1000.00",
        "guide_price": "1200.00",
        "tax_rate": "6.00",
        "cost_price": "800.00",
        "params": "{\"source\": \"api-autotest\"}",
        "default_remark": "销售商品接口自动化临时数据，可安全删除",
        "status": "enabled",
        "sort_order": 99,
        "images": [],
    }
    body.update(overrides)
    return body


def _create_temporary_product(client, **overrides):
    """创建唯一临时商品并校验初始状态。"""
    body = _product_body(**overrides)
    payload = _assert_success(client.post(SALES_PRODUCTS_URL, json=body), "创建临时销售商品")
    product = payload["data"]
    _assert_product_shape(product, "创建临时销售商品")
    assert product["name"] == body["name"], "创建后的商品名称不正确：%s" % product
    assert product["status"] == body["status"], "创建后的商品状态不正确：%s" % product
    return product


def _cleanup_temporary_product(client, product_id):
    """临时商品按业务规则先停用，再物理删除。"""
    if not product_id:
        return
    try:
        client.post("%s/%s/disable" % (SALES_PRODUCTS_URL, product_id))
        client.delete("%s/%s" % (SALES_PRODUCTS_URL, product_id))
    except Exception:
        pass


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-销售商品")
class Test销售商品查询与校验:
    """认证、列表、选项、编号和参数校验。"""

    @allure.feature("访问权限")
    def test_未登录访问销售商品列表_返回令牌无效(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        with allure.step("不携带 Authorization 请求销售商品列表"):
            response = anonymous_client.get(SALES_PRODUCTS_URL)
        _assert_error_code(response, "未登录获取销售商品列表", TOKEN_INVALID_CODE)

    @allure.feature("查询与选项")
    def test_销售商品列表_选项与下一编号返回完整结构(self, sales_product_client):
        with allure.step("查询默认销售商品列表"):
            list_payload = _assert_success(
                sales_product_client.get(SALES_PRODUCTS_URL, params={"page": 1, "page_size": 10}),
                "获取销售商品列表",
            )
        _assert_page_payload(list_payload, "获取销售商品列表", expected_page=1, expected_page_size=10)

        with allure.step("查询软件类商品下一编号"):
            next_code_payload = _assert_success(
                sales_product_client.get(SALES_PRODUCT_NEXT_CODE_URL, params={"category": "software"}),
                "获取销售商品下一编号",
            )
        next_code = (next_code_payload["data"] or {}).get("product_code")
        assert isinstance(next_code, str) and next_code.strip(), "下一商品编码为空：%s" % next_code_payload

        with allure.step("查询仅包含启用商品的报价选项"):
            options_payload = _assert_success(
                sales_product_client.get(SALES_PRODUCT_OPTIONS_URL, params={"page": 1, "page_size": 10}),
                "获取销售商品选项",
            )
        options_data = _assert_page_payload(options_payload, "获取销售商品选项", expected_page=1, expected_page_size=10)
        assert all(item.get("status") == "enabled" for item in options_data["items"]), options_data

    @allure.feature("参数校验")
    def test_销售商品创建_必填字段价格范围和不存在详情校验(self, sales_product_client):
        invalid_requests = [
            ("缺少全部必填字段", {}),
            (
                "默认价格为负数",
                {
                    "name": "AT-非法价格商品",
                    "category": "software",
                    "default_price": "-1",
                },
            ),
        ]
        for action, body in invalid_requests:
            with allure.step("创建销售商品：%s" % action):
                response = sales_product_client.post(SALES_PRODUCTS_URL, json=body)
            _assert_error_code(response, "创建销售商品%s" % action, INVALID_PARAMS_CODE)

        with allure.step("查询不存在的商品详情"):
            detail_response = sales_product_client.get("%s/%s" % (SALES_PRODUCTS_URL, 2147483647))
        _assert_error_code(detail_response, "查询不存在的销售商品详情", NOT_FOUND_CODE)

    @allure.feature("兼容接口")
    def test_销售商品导入接口_返回当前版本不支持(self, sales_product_client):
        with allure.step("调用已废弃的商品导入入口"):
            response = sales_product_client.post(SALES_PRODUCT_IMPORT_URL, json={})
        _assert_error_code(response, "调用销售商品导入接口", OPERATION_NOT_ALLOWED_CODE)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-销售商品")
class Test销售商品业务链路:
    """创建、筛选、编辑、图片、启停、删除和唯一性完整链路。"""

    @allure.feature("商品生命周期")
    def test_销售商品创建_筛选编辑图片详情与清理(self, sales_product_client):
        _require_write_tests()
        product_id = None
        try:
            product = _create_temporary_product(sales_product_client)
            product_id = product["id"]

            with allure.step("按关键字、类别和启用状态组合筛选商品"):
                list_payload = _assert_success(
                    sales_product_client.get(
                        SALES_PRODUCTS_URL,
                        params={
                            "keyword": product["name"],
                            "category": "software",
                            "status": "enabled",
                            "page": 1,
                            "page_size": 10,
                        },
                    ),
                    "组合筛选销售商品",
                )
            list_data = _assert_page_payload(list_payload, "组合筛选销售商品", expected_page=1, expected_page_size=10)
            assert any(item.get("id") == product_id for item in list_data["items"]), list_data

            updated_name = "AT-销售商品已编辑-%s" % uuid4().hex[:10]
            with allure.step("更新商品名称、价格、规格、排序和使用场景"):
                update_payload = _assert_success(
                    sales_product_client.put(
                        "%s/%s" % (SALES_PRODUCTS_URL, product_id),
                        json={
                            "name": updated_name,
                            "spec_name": "专业版-%s" % uuid4().hex[:8],
                            "unit": "年",
                            "usage_scene": "接口自动化编辑验证",
                            "default_price": "2000.00",
                            "guide_price": "2400.00",
                            "tax_rate": "13.00",
                            "cost_price": "1500.00",
                            "default_remark": "销售商品编辑后的自动化备注",
                            "sort_order": 88,
                        },
                    ),
                    "更新销售商品",
                )
            updated = update_payload["data"]
            _assert_product_shape(updated, "更新销售商品", expected_product_id=product_id)
            assert updated["name"] == updated_name and updated["unit"] == "年", updated
            assert float(updated["default_price"]) == 2000.0, updated
            assert float(updated["guide_price"]) == 2400.0, updated
            assert float(updated["tax_rate"]) == 13.0, updated
            assert updated["sort_order"] == 88, updated

            images = [
                {"image_url": "https://example.com/at-sales-product-2.png", "sort_order": 2},
                {"image_url": "https://example.com/at-sales-product-1.png", "sort_order": 1},
            ]
            with allure.step("绑定已上传的商品图片 URL"):
                image_payload = _assert_success(
                    sales_product_client.post(
                        "%s/%s/images" % (SALES_PRODUCTS_URL, product_id),
                        json={"images": images},
                    ),
                    "绑定销售商品图片",
                )
            product_with_images = image_payload["data"]
            _assert_product_shape(product_with_images, "绑定销售商品图片", expected_product_id=product_id)
            assert [item.get("sort_order") for item in product_with_images["images"]] == [1, 2], product_with_images

            with allure.step("查询包含图片的销售商品详情"):
                detail_payload = _assert_success(
                    sales_product_client.get("%s/%s" % (SALES_PRODUCTS_URL, product_id)),
                    "获取销售商品详情",
                )
            detail = detail_payload["data"]
            _assert_product_shape(detail, "获取销售商品详情", expected_product_id=product_id)
            assert detail["name"] == updated_name and len(detail["images"]) == 2, detail
        finally:
            _cleanup_temporary_product(sales_product_client, product_id)

    @allure.feature("启停与删除")
    def test_销售商品状态_选项可见性与停用后删除约束(self, sales_product_client):
        _require_write_tests()
        product_id = None
        try:
            product = _create_temporary_product(sales_product_client)
            product_id = product["id"]

            with allure.step("启用状态商品直接删除应被拒绝"):
                delete_enabled_response = sales_product_client.delete("%s/%s" % (SALES_PRODUCTS_URL, product_id))
            _assert_error_code(delete_enabled_response, "删除启用状态销售商品", OPERATION_NOT_ALLOWED_CODE)

            with allure.step("停用商品并校验选项中不再可见"):
                disable_payload = _assert_success(
                    sales_product_client.post("%s/%s/disable" % (SALES_PRODUCTS_URL, product_id)),
                    "停用销售商品",
                )
                options_payload = _assert_success(
                    sales_product_client.get(
                        SALES_PRODUCT_OPTIONS_URL,
                        params={"keyword": product["name"], "page": 1, "page_size": 10},
                    ),
                    "查询停用后的销售商品选项",
                )
            assert disable_payload["data"].get("status") == "disabled", disable_payload
            options_data = _assert_page_payload(options_payload, "查询停用后的销售商品选项", expected_page=1, expected_page_size=10)
            assert all(item.get("id") != product_id for item in options_data["items"]), options_data

            with allure.step("重新启用商品后应回到报价选项中"):
                enable_payload = _assert_success(
                    sales_product_client.post("%s/%s/enable" % (SALES_PRODUCTS_URL, product_id)),
                    "启用销售商品",
                )
                restored_options_payload = _assert_success(
                    sales_product_client.get(
                        SALES_PRODUCT_OPTIONS_URL,
                        params={"keyword": product["name"], "page": 1, "page_size": 10},
                    ),
                    "查询启用后的销售商品选项",
                )
            assert enable_payload["data"].get("status") == "enabled", enable_payload
            restored_options = _assert_page_payload(
                restored_options_payload,
                "查询启用后的销售商品选项",
                expected_page=1,
                expected_page_size=10,
            )
            assert any(item.get("id") == product_id for item in restored_options["items"]), restored_options

            with allure.step("再次停用后删除临时商品"):
                _assert_success(
                    sales_product_client.post("%s/%s/disable" % (SALES_PRODUCTS_URL, product_id)),
                    "再次停用销售商品",
                )
                delete_payload = _assert_success(
                    sales_product_client.delete("%s/%s" % (SALES_PRODUCTS_URL, product_id)),
                    "删除停用销售商品",
                )
            assert delete_payload["data"].get("id") == product_id, delete_payload
            assert delete_payload["data"].get("deleted") is True, delete_payload
            deleted_product_id = product_id
            product_id = None
            with allure.step("删除后查询详情应返回不存在"):
                detail_response = sales_product_client.get("%s/%s" % (SALES_PRODUCTS_URL, deleted_product_id))
            _assert_error_code(detail_response, "查询已删除销售商品", NOT_FOUND_CODE)
        finally:
            _cleanup_temporary_product(sales_product_client, product_id)

    @allure.feature("唯一性")
    def test_销售商品名称与规格_组合不可重复(self, sales_product_client):
        _require_write_tests()
        product_id = None
        try:
            name = "AT-销售商品重名-%s" % uuid4().hex[:10]
            spec_name = "唯一规格-%s" % uuid4().hex[:8]
            product = _create_temporary_product(sales_product_client, name=name, spec_name=spec_name)
            product_id = product["id"]
            with allure.step("使用相同名称和规格再次创建销售商品"):
                duplicate_response = sales_product_client.post(
                    SALES_PRODUCTS_URL,
                    json=_product_body(name=name, spec_name=spec_name),
                )
            _assert_error_code(duplicate_response, "创建名称规格重复的销售商品", NAME_ALREADY_EXISTS_CODE)
        finally:
            _cleanup_temporary_product(sales_product_client, product_id)
