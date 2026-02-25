# -*- encoding=utf8 -*-
"""
采购订单模块接口自动化测试 - 前两个接口
- 登录接口：POST /api/users/auth/login 获取 JWT，供后续订单接口使用
- 接口1：订单状态列表 GET /api/canteen-management/order-status/
- 接口2：配送商与品类（下单用） GET /api/canteen-management/order/distributor-cate/
文档约定：code === 0 表示成功；需登录，请求头携带 JWT：Authorization: Bearer <token>
"""
__author__ = "Administrator"

import logging
import allure
import pytest

from utils.http_client import client

logger = logging.getLogger(__name__)

# 登录接口（与 project_information.base_url 拼接；注意：无尾部斜杠，与文档一致）
LOGIN_URL = "/api/users/auth/login"
LOGIN_BODY = {
    "username": "13100002222",
    "password": "123456",
    "department_type": "school",
    "department_id": 2,
}

# 订单模块接口路径（与 project_information.base_url 拼接；路径结尾无斜杠）
ORDER_STATUS_URL = "/api/canteen-management/order-status"
ORDER_DISTRIBUTOR_CATE_URL = "/api/canteen-management/order/distributor-cate"

# 若已在 default_headers 或此处配置了 Token，可优先使用，否则走登录接口获取
ORDER_API_HEADERS = None


def _get_headers():
    """返回请求头，优先使用订单模块专用 headers（与 client 默认 headers 合并）"""
    return (ORDER_API_HEADERS or {}).copy()


def get_token():
    """
    调用登录接口获取 JWT Token（接口关联）。
    请求：POST /api/users/auth/login，body 为 LOGIN_BODY。
    返回：token 字符串；失败时抛出 AssertionError。
    """
    with allure.step("调用登录接口获取 Token"):
        resp = client.post(LOGIN_URL, json=LOGIN_BODY)
    # 调试：404 时打印实际请求 URL
    assert resp.status_code == 200, (
        f"登录请求失败: HTTP {resp.status_code}，请求 URL: {resp.url}，"
        f"响应: {resp.text[:500] if resp.text else '空'}"
    )
    data = resp.json()
    assert data.get("code") == 0, (
        f"登录业务失败: code={data.get('code')}, message={data.get('message')}，"
        f"响应 keys: {list(data.keys())}"
    )
    # 常见返回：data.token / data.access / data.access_token / 顶层 token
    payload = data.get("data")
    if payload is None:
        payload = data
    token = (
        (payload.get("token") if isinstance(payload, dict) else None)
        or (payload.get("access") if isinstance(payload, dict) else None)
        or (payload.get("access_token") if isinstance(payload, dict) else None)
        or data.get("token")
        or data.get("access")
    )
    if not token:
        logger.error("登录响应中未找到 token，data.keys=%s, data.data keys=%s",
                     list(data.keys()),
                     list(data.get("data") or {}).keys() if isinstance(data.get("data"), dict) else "data 非 dict")
        raise AssertionError(
            f"登录响应中未找到 token，请检查返回结构。data keys: {list(data.keys())}, "
            f"data.data: {type(data.get('data'))} {list((data.get('data') or {}).keys()) if isinstance(data.get('data'), dict) else data.get('data')}"
        )
    return token


def _assert_200_or_404_msg(resp, msg_prefix="请求"):
    """校验状态码为 200，否则抛出包含请求 URL 的断言信息（便于排查 404）"""
    if resp.status_code != 200:
        req_headers = getattr(getattr(resp, "request", None), "headers", None) or {}
        has_auth = "Authorization" in req_headers or "authorization" in str(req_headers).lower()
        raise AssertionError(
            f"{msg_prefix} 期望 200，实际 {resp.status_code}，"
            f"请求 URL: {resp.url}，"
            f"请求头含 Authorization: {has_auth}，"
            f"响应: {(resp.text or '')[:300]}"
        )


@allure.parent_suite("接口自动化")
@allure.suite("采购订单模块")
class Test订单状态与配送商品类:
    """订单状态列表与配送商品类接口测试（依赖登录获取 Token）"""

    @pytest.fixture(scope="class", autouse=True)
    def 订单带token(self):
        """
        类级别 fixture：先调用登录接口获取 Token，并写入 client 请求头，
        本类中所有用例将自动携带该 Token（接口关联）。
        """
        token = get_token()
        client.headers["Authorization"] = f"Bearer {token}"
        logger.info("已从登录接口获取 token 并写入 client.headers，Authorization 已设置")
        yield
        client.headers.pop("Authorization", None)

    # ---------- 调试：验证登录与请求 ----------
    @allure.feature("登录与 Token")
    def test_00_登录获取token(self):
        """【调试】验证登录成功且订单接口请求时携带 Token 和正确 URL"""
        with allure.step("确认 client 已携带 Authorization（由 fixture 注入）"):
            auth = client.headers.get("Authorization") or ""
            assert auth.startswith("Bearer "), f"未找到 Bearer Token，client.headers 含: {list(client.headers.keys())}"
        with allure.step("请求订单状态列表，检查实际 URL 与状态码"):
            # 不传 headers，确保只用 client.headers（含 Token）
            resp = client.get(ORDER_STATUS_URL, params={})
        with allure.step("若为 404 则输出请求 URL 和响应便于排查"):
            _assert_200_or_404_msg(resp, "订单状态列表")
        data = resp.json()
        assert "data" in data, f"响应应含 data，keys: {list(data.keys())}"
        assert data.get("code") == 0, f"业务码应为 0，实际 {data.get('code')}，message: {data.get('message')}"

    # ---------- 接口1：订单状态列表 ----------
    @allure.feature("订单状态列表")
    def test_订单状态列表_默认(self):
        """订单状态列表 - 无参数，默认返回"""
        with allure.step("发送 GET 请求（无查询参数，使用 client 自带 Token）"):
            resp = client.get(ORDER_STATUS_URL, params={})
        with allure.step("校验状态码为 200"):
            _assert_200_or_404_msg(resp, "订单状态列表")
        with allure.step("校验响应体结构：code=0、message、data 为数组"):
            data = resp.json()
            assert "code" in data, "响应中应包含 code"
            assert "message" in data, "响应中应包含 message"
            assert "data" in data, "响应中应包含 data"
            assert data["code"] == 0, f"业务码应为 0 表示成功，实际 {data.get('code')}，message: {data.get('message')}"
            assert isinstance(data["data"], list), "data 应为列表"

        with allure.step("校验 data 中每项包含 id、name、sign、sequence、active（文档约定字段）"):
            for item in data["data"]:
                assert "id" in item, "状态项应包含 id"
                assert "name" in item, "状态项应包含 name"
                assert "sign" in item, "状态项应包含 sign"
                assert "sequence" in item, "状态项应包含 sequence"
                assert "active" in item, "状态项应包含 active"

    @allure.feature("订单状态列表")
    def test_订单状态列表_按名称过滤(self):
        """订单状态列表 - 按状态名称过滤（name）"""
        with allure.step("发送 GET 请求（name=待提交）"):
            resp = client.get(ORDER_STATUS_URL, params={"name": "待提交"})
        with allure.step("校验状态码为 200"):
            _assert_200_or_404_msg(resp, "订单状态列表(name)")
        with allure.step("校验业务码为 0 且 data 为列表"):
            data = resp.json()
            assert data.get("code") == 0, f"业务码应为 0，实际 {data.get('code')}，message: {data.get('message')}"
            assert isinstance(data.get("data"), list), "data 应为列表"

    @allure.feature("订单状态列表")
    def test_订单状态列表_按标记过滤(self):
        """订单状态列表 - 按状态标记过滤（sign=to_pending）"""
        with allure.step("发送 GET 请求（sign=to_pending）"):
            resp = client.get(ORDER_STATUS_URL, params={"sign": "to_pending"})
        with allure.step("校验状态码为 200"):
            _assert_200_or_404_msg(resp, "订单状态列表(sign)")
        data = resp.json()
        assert data.get("code") == 0, f"业务码应为 0，实际 {data.get('code')}"
        assert isinstance(data.get("data"), list), "data 应为列表"

    @allure.feature("订单状态列表")
    def test_订单状态列表_排序(self):
        """订单状态列表 - 按 sequence 排序"""
        with allure.step("发送 GET 请求（ordering=sequence）"):
            resp = client.get(ORDER_STATUS_URL, params={"ordering": "sequence"})
        with allure.step("校验状态码为 200"):
            _assert_200_or_404_msg(resp, "订单状态列表(ordering)")
        data = resp.json()
        assert data.get("code") == 0, f"业务码应为 0，实际 {data.get('code')}"
        assert isinstance(data.get("data"), list), "data 应为列表"

    @allure.feature("订单状态列表")
    def test_订单状态列表_按有效过滤(self):
        """订单状态列表 - 按是否有效过滤（active=true）"""
        with allure.step("发送 GET 请求（active=true）"):
            resp = client.get(ORDER_STATUS_URL, params={"active": "true"})
        with allure.step("校验状态码为 200"):
            _assert_200_or_404_msg(resp, "订单状态列表(active)")
        data = resp.json()
        assert data.get("code") == 0, f"业务码应为 0，实际 {data.get('code')}"
        assert isinstance(data.get("data"), list), "data 应为列表"

    # ---------- 接口2：配送商与品类（下单用） ----------
    @allure.feature("配送商与品类（下单用）")
    def test_配送商品类列表(self):
        """配送商与品类 - 无参数，根据 token 解析食堂返回配送商及品类"""
        with allure.step("发送 GET 请求（无参数，食堂从 token 解析）"):
            resp = client.get(ORDER_DISTRIBUTOR_CATE_URL, params={})
        with allure.step("校验状态码为 200 或 403（仅学校用户可访问）"):
            if resp.status_code not in (200, 403):
                _assert_200_or_404_msg(resp, "配送商与品类")

        if resp.status_code == 403:
            pytest.skip("当前用户非学校用户，无权限访问配送商与品类接口")

        with allure.step("校验响应体结构：code=0、data 为数组"):
            data = resp.json()
            assert "code" in data, "响应中应包含 code"
            assert "data" in data, "响应中应包含 data"
            assert data["code"] == 0, f"业务码应为 0，实际 {data.get('code')}，message: {data.get('message')}"
            assert isinstance(data["data"], list), "data 应为列表"

        with allure.step("校验 data 中每项包含 id、name、category_info（文档约定字段）"):
            for item in data["data"]:
                assert "id" in item, "配送商项应包含 id"
                assert "name" in item, "配送商项应包含 name"
                assert "category_info" in item, "配送商项应包含 category_info"
                assert isinstance(item["category_info"], list), "category_info 应为列表"
                for cat in item["category_info"]:
                    assert "id" in cat, "品类项应包含 id"
                    assert "name" in cat, "品类项应包含 name"
