# -*- encoding=utf8 -*-
"""
接口自动化测试用例模板
- 演示 GET / POST 请求与断言
- 使用 Allure 装饰器与 step 记录步骤
"""
__author__ = "Administrator"

import allure
import pytest

from utils.http_client import client

# 可选：使用 config 中的 base_url 覆盖（当前示例使用 httpbin）
# from config.project_information import base_url


@allure.parent_suite("接口自动化")
@allure.suite("示例接口")
class TestApiDemo:
    """接口测试用例模板类"""

    @allure.feature("GET 请求")
    def test_get_request(self):
        """示例：GET 请求并校验状态码与响应体"""
        with allure.step("发送 GET 请求"):
            resp = client.get("/get", params={"key": "value"})
        with allure.step("校验状态码为 200"):
            assert resp.status_code == 200
        with allure.step("校验响应中包含请求参数"):
            data = resp.json()
            assert "args" in data
            assert data["args"].get("key") == "value"

    @allure.feature("POST 请求")
    def test_post_request(self):
        """示例：POST JSON 并校验响应"""
        body = {"name": "test", "id": 1}
        with allure.step("发送 POST 请求"):
            resp = client.post("/post", json=body)
        with allure.step("校验状态码为 200"):
            assert resp.status_code == 200
        with allure.step("校验响应体中的 JSON 与请求一致"):
            data = resp.json()
            assert data.get("json") == body

    @allure.feature("状态码校验")
    def test_status_code(self):
        """示例：校验接口返回指定状态码"""
        with allure.step("请求 /status/200"):
            resp = client.get("/status/200")
        with allure.step("校验状态码为 200"):
            assert resp.status_code == 200
