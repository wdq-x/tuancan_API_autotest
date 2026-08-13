# -*- coding: utf-8 -*-
"""管理平台认证与通用附件接口自动化测试。

认证用例使用独立登录态，避免注销接口影响同一轮其他模块的共享 Token。附件用例
上传带 ``AT-`` 前缀的临时文本文件，验证下载内容；仅当当前存储后端返回
``object_name`` 时才调用 MinIO 删除接口。若服务配置的是本地回退存储，接口本身
没有 ``local_path`` 删除能力，测试会明确跳过该存储专用分支而不留下误导性断言。
"""
from uuid import uuid4

import allure
import pytest
import requests

from config.project_information import MANAGEMENT_TEST_ACCOUNT, default_headers
from utils.api_test_support import assert_auth_required, assert_client_error, assert_success, management_client
from utils.http_client import HttpClient, NO_PROXIES


LOGIN_URL = "/v1/login"
USER_INFO_URL = "/v1/user/info"
REFRESH_TOKEN_URL = "/v1/refresh-token"
PERMISSIONS_URL = "/v1/auth/permissions"
LOGOUT_URL = "/v1/logout"
HEALTH_TEST_URL = "/v1/test"
UPLOAD_URL = "/v1/upload"
DOWNLOAD_URL = "/v1/upload/download"
DELETE_FILE_URL = "/v1/delete"


def _login_payload(client_type="pc"):
    account = MANAGEMENT_TEST_ACCOUNT or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "").strip()
    if not username or not password:
        pytest.skip("MANAGEMENT_TEST_USERNAME / MANAGEMENT_TEST_PASSWORD is not configured")

    client = HttpClient(headers=default_headers.copy())
    payload = assert_success(
        client.post(LOGIN_URL, json={"username": username, "password": password, "client_type": client_type}),
        "log in for auth API regression",
    )
    data = payload.get("data") or {}
    assert isinstance(data.get("access_token"), str) and data["access_token"], payload
    assert isinstance(data.get("refresh_token"), str) and data["refresh_token"], payload
    return client, data


def _upload_text_file(client, file_name, content):
    headers = {key: value for key, value in client.headers.items() if key.lower() != "content-type"}
    response = requests.post(
        client._url(UPLOAD_URL),
        data={"folder": "AT-auth-attachments"},
        files={"files": (file_name, content, "text/plain")},
        headers=headers,
        timeout=client.timeout,
        proxies=NO_PROXIES,
    )
    payload = assert_success(response, "upload AT attachment")
    files = (payload.get("data") or {}).get("files") or []
    assert len(files) == 1 and isinstance(files[0], dict), payload
    uploaded = files[0]
    assert uploaded.get("name") == file_name, uploaded
    assert uploaded.get("object_name") or uploaded.get("local_path"), uploaded
    return uploaded


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与权限-认证和附件")
class Test认证接口:
    @allure.feature("认证状态")
    def test_用户信息_权限_刷新令牌与测试接口(self):
        client, login_data = _login_payload()
        client.headers["Authorization"] = "Bearer %s" % login_data["access_token"]
        try:
            with allure.step("读取当前登录用户信息"):
                info_payload = assert_success(client.get(USER_INFO_URL), "get current user info")
            info = info_payload.get("data") or {}
            assert isinstance(info.get("id"), int) and info["id"] > 0, info_payload
            assert info.get("is_active") is True, info_payload

            with allure.step("读取当前用户权限码"):
                permissions_payload = assert_success(client.get(PERMISSIONS_URL), "get current user permissions")
            permissions = (permissions_payload.get("data") or {}).get("permissions")
            assert isinstance(permissions, list), permissions_payload
            assert all(isinstance(code, str) and code for code in permissions), permissions_payload

            with allure.step("使用 refresh_token 换取新的 access_token"):
                refresh_payload = assert_success(
                    client.post(REFRESH_TOKEN_URL, json={"refresh_token": login_data["refresh_token"]}),
                    "refresh access token",
                )
            refreshed = refresh_payload.get("data") or {}
            assert isinstance(refreshed.get("access_token"), str) and refreshed["access_token"], refresh_payload
            assert refreshed.get("token_type") == "Bearer", refresh_payload

            with allure.step("调用无鉴权依赖的服务测试接口"):
                health_payload = client.get(HEALTH_TEST_URL).json()
            assert health_payload.get("code") == 200, health_payload
            assert isinstance((health_payload.get("data") or {}).get("timestamp"), str), health_payload
        finally:
            client.headers.pop("Authorization", None)

    @allure.feature("认证状态")
    def test_注销接口_按令牌存储配置返回可验证结果(self):
        """Redis Token Store 启用时验证撤销；禁用时验证当前明确的失败契约。"""
        client, login_data = _login_payload(client_type="pc")
        client.headers["Authorization"] = "Bearer %s" % login_data["access_token"]
        try:
            with allure.step("注销独立 PC 登录态"):
                logout_response = client.post(LOGOUT_URL)
            logout_payload = logout_response.json()
            if logout_payload.get("code") == 20000:
                assert logout_payload.get("data") is None, logout_payload

                with allure.step("使用已注销令牌访问当前用户信息"):
                    response = client.get(USER_INFO_URL)
                assert_auth_required(response, "access user info after logout")
            else:
                assert_client_error(
                    logout_response,
                    "logout when token store is disabled",
                    code=5106,
                    msg="登出失败",
                    data_type=type(None),
                )
        finally:
            client.headers.pop("Authorization", None)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与权限-认证和附件")
class Test通用附件接口:
    @allure.feature("通用附件")
    def test_附件上传_下载并按存储能力删除(self):
        client = management_client()
        object_name = None
        try:
            file_name = "AT-auth-attachment-%s.txt" % uuid4().hex[:12]
            content = b"AT attachment download verification"
            with allure.step("上传 AT 临时文本附件"):
                uploaded = _upload_text_file(client, file_name, content)
            object_name = uploaded.get("object_name")

            params = {"filename": file_name}
            if object_name:
                params["object_name"] = object_name
            else:
                params["local_path"] = uploaded["local_path"]
            with allure.step("按上传返回的对象标识下载附件"):
                download_response = client.get(DOWNLOAD_URL, params=params)
            assert download_response.status_code == 200, download_response.text[:500]
            assert download_response.content == content, download_response.content[:500]
            assert "attachment" in (download_response.headers.get("Content-Disposition") or "").lower()

            if not object_name:
                pytest.skip("当前服务使用本地附件回退存储，/v1/delete 仅支持 object_name，无法通过 API 清理 local_path")

            with allure.step("删除 MinIO 临时附件"):
                delete_payload = assert_success(
                    client.delete(DELETE_FILE_URL, params={"object_name": object_name}),
                    "delete uploaded AT attachment",
                )
            assert (delete_payload.get("data") or {}).get("deleted") is True, delete_payload
            object_name = None
        finally:
            if object_name:
                try:
                    client.delete(DELETE_FILE_URL, params={"object_name": object_name})
                except Exception:
                    pass
