# -*- coding: utf-8 -*-
"""Channel-account authentication boundaries.

Channel accounts use a separate identity model from management users. The
repository has no channel-account credential secret, so this suite validates
the public failure and token-boundary contracts without inventing credentials.
"""
import allure

from utils.api_test_support import assert_auth_required, assert_validation_error
from utils.http_client import HttpClient


BASE_URL = "/v1/channel-auth"


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-售后与协同-渠道账号认证")
class Test渠道账号认证:
    @allure.feature("登录校验")
    @allure.title("渠道账号登录缺少凭据被拒绝")
    def test_channel_login_rejects_missing_credentials(self):
        assert_validation_error(
            HttpClient().post(BASE_URL + "/login", json={}),
            "channel login without credentials",
            (("body", "phone"), ("body", "password")),
        )

    @allure.feature("令牌边界")
    @allure.title("渠道账号接口未登录访问被拒绝")
    def test_channel_account_endpoints_reject_anonymous_access(self):
        client = HttpClient()
        for suffix, action in (
            ("/me", "get anonymous channel account profile"),
            ("/permissions", "get anonymous channel account permissions"),
            ("/logout", "log out anonymous channel account"),
        ):
            response = client.post(BASE_URL + suffix) if suffix == "/logout" else client.get(BASE_URL + suffix)
            assert_auth_required(response, action)
