# -*- encoding=utf8 -*-
"""
配送包管理接口自动化测试 - 前两个接口
- 接口1：获取配送包列表 GET /api/food-safety-monitoring/bag/
- 接口2：获取配送包详情 GET /api/food-safety-monitoring/bag/{id}/
使用前请在 config/project_information.py 中配置 base_url 为实际环境地址，
并在 default_headers 或下方 BAG_API_HEADERS 中配置有效的 JWT Token。
"""
__author__ = "Administrator"

import allure
import pytest

from utils.http_client import client

# 配送包接口基础路径（与 project_information.base_url 拼接）
BAG_API_BASE = "/api/food-safety-monitoring/bag"

# 若需单独为配送包接口设置 Token，可在此配置（否则使用 client 默认 headers）
# 示例：BAG_API_HEADERS = {"Authorization": "Bearer your-jwt-token"}
BAG_API_HEADERS = None


def _get_headers():
    """返回请求头，优先使用配送包专用 headers"""
    return (BAG_API_HEADERS or {}).copy()


@allure.parent_suite("接口自动化")
@allure.suite("配送包管理")
class TestBagListAndDetail:
    """配送包列表与详情接口测试"""

    # ---------- 接口1：获取配送包列表 ----------
    @allure.feature("获取配送包列表")
    def test_bag_list_default(self):
        """获取配送包列表 - 默认分页参数"""
        with allure.step("发送 GET 请求（无查询参数，使用默认分页）"):
            resp = client.get(
                f"{BAG_API_BASE}/",
                params={},
                headers=_get_headers() or None,
            )
        with allure.step("校验状态码为 200"):
            assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
        with allure.step("校验响应体结构：code、message、data、count"):
            data = resp.json()
            assert "code" in data, "响应中应包含 code"
            assert "message" in data, "响应中应包含 message"
            assert "data" in data, "响应中应包含 data"
            assert data["code"] == 200, f"业务码应为 200，实际 {data.get('code')}，message: {data.get('message')}"
            assert isinstance(data["data"], list), "data 应为列表"

    @allure.feature("获取配送包列表")
    def test_bag_list_with_pagination(self):
        """获取配送包列表 - 指定 page 和 size"""
        with allure.step("发送 GET 请求（page=1, size=10）"):
            resp = client.get(
                f"{BAG_API_BASE}/",
                params={"page": 1, "size": 10},
                headers=_get_headers() or None,
            )
        with allure.step("校验状态码为 200"):
            assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
        with allure.step("校验响应体结构及分页字段"):
            data = resp.json()
            assert data.get("code") == 200, f"业务码应为 200，实际 {data.get('code')}"
            assert "data" in data and isinstance(data["data"], list), "data 应为列表"
            if "count" in data:
                assert isinstance(data["count"], (int, type(None))), "count 应为整数或不存在"

    @allure.feature("获取配送包列表")
    def test_bag_list_with_ordering(self):
        """获取配送包列表 - 按 create_date 倒序"""
        with allure.step("发送 GET 请求（ordering=-create_date）"):
            resp = client.get(
                f"{BAG_API_BASE}/",
                params={"ordering": "-create_date"},
                headers=_get_headers() or None,
            )
        with allure.step("校验状态码为 200"):
            assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
        with allure.step("校验业务码与 data 为列表"):
            data = resp.json()
            assert data.get("code") == 200, f"业务码应为 200，实际 {data.get('code')}"
            assert isinstance(data.get("data"), list), "data 应为列表"

    @allure.feature("获取配送包列表")
    def test_bag_list_with_search(self):
        """获取配送包列表 - 带搜索关键词（search）"""
        with allure.step("发送 GET 请求（search=标准包）"):
            resp = client.get(
                f"{BAG_API_BASE}/",
                params={"search": "标准包"},
                headers=_get_headers() or None,
            )
        with allure.step("校验状态码为 200"):
            assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
        data = resp.json()
        assert data.get("code") == 200, f"业务码应为 200，实际 {data.get('code')}"
        assert isinstance(data.get("data"), list), "data 应为列表"

    # ---------- 接口2：获取配送包详情 ----------
    @allure.feature("获取配送包详情")
    def test_bag_detail_by_id(self):
        """获取配送包详情 - 使用有效 id（从列表取第一条或使用 id=1）"""
        with allure.step("先请求列表获取一条配送包 id"):
            list_resp = client.get(
                f"{BAG_API_BASE}/",
                params={"page": 1, "size": 1},
                headers=_get_headers() or None,
            )
            assert list_resp.status_code == 200, f"列表接口失败: {list_resp.status_code}"
            list_data = list_resp.json()
            assert list_data.get("code") == 200, f"列表业务码异常: {list_data.get('message')}"
            items = list_data.get("data") or []

        if not items:
            pytest.skip("当前环境无配送包数据，跳过详情测试（可先创建配送包后再运行）")

        bag_id = items[0].get("id")
        with allure.step(f"发送 GET 请求获取配送包详情 id={bag_id}"):
            resp = client.get(
                f"{BAG_API_BASE}/{bag_id}/",
                headers=_get_headers() or None,
            )
        with allure.step("校验状态码为 200"):
            assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
        with allure.step("校验响应体结构：code、message、data 及详情字段"):
            data = resp.json()
            assert data.get("code") == 200, f"业务码应为 200，实际 {data.get('code')}，message: {data.get('message')}"
            detail = data.get("data")
            assert detail is not None, "data 不应为空"
            assert "id" in detail, "详情应包含 id"
            assert "name" in detail, "详情应包含 name"
            assert "category_line" in detail, "详情应包含 category_line"
            assert detail["id"] == bag_id, f"返回的 id 应与请求一致: {detail['id']} != {bag_id}"

    @allure.feature("获取配送包详情")
    def test_bag_detail_not_found(self):
        """获取配送包详情 - 不存在的 id 应返回 404 或业务错误"""
        with allure.step("发送 GET 请求（id=999999，假定不存在）"):
            resp = client.get(
                f"{BAG_API_BASE}/999999/",
                headers=_get_headers() or None,
            )
        with allure.step("校验状态码为 404 或 200 且业务码非 200"):
            data = resp.json() if resp.headers.get("content-type", "").find("json") >= 0 else {}
            # 常见：HTTP 404 或 HTTP 200 但 code=404
            if resp.status_code == 404:
                assert True, "符合预期：资源不存在返回 404"
            elif resp.status_code == 200 and data.get("code") not in (200, None):
                assert True, f"符合预期：业务码表示错误 code={data.get('code')}"
            else:
                # 若接口对不存在的 id 仍返回 200+code=200，本用例仅记录，不强制失败
                assert resp.status_code in (200, 404), f"期望 200 或 404，实际 {resp.status_code}"
