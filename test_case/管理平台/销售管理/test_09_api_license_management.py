# -*- coding: utf-8 -*-
"""管理平台销售管理-License 与客户 License 同步接口自动化测试。

覆盖 License 生成、下载、验证、客户 License 查询/校验，以及客户 License
同步的认证、参数、客户信息和远端失败边界。测试只创建 ``AT-`` 临时客户。
"""
from datetime import date, timedelta
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS, default_headers
from utils.api_test_support import (
    assert_auth_required,
    assert_client_error,
    assert_success,
    assert_validation_error,
    management_client,
    parse_json,
)
from utils.http_client import HttpClient


CUSTOMERS_URL = "/v1/customers"
LICENSE_URL = "/v1/license"
CUSTOMER_SYNC_URL = "/v1/customers/sync"

SUCCESS_CODE = 20000
CUSTOMER_NOT_FOUND_CODE = 5300
CUSTOMER_LICENSE_MISSING_CODE = 5302
CUSTOMER_DOMAIN_MISSING_CODE = 5303
LICENSE_INVALID_CODE = 5304
OPERATION_FAILED_CODE = 5106
INTERNAL_ERROR_CODE = 6001


def _require_write_tests():
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _customer_body(**overrides):
    body = {
        "name": "AT-License客户-%s" % uuid4().hex[:12],
        "deployment_type": "public_cloud",
        "customer_type": "school",
        "manager_name": "License接口自动化联系人",
        "manager_phone": "13900000000",
        "service_period": 12,
        "valid_start": date.today().isoformat(),
        "valid_end": (date.today() + timedelta(days=365)).isoformat(),
        "dining_limit": 1,
        "pos_count": 1,
        "remarks": "License接口自动化临时客户",
        "attachments": [],
        "call_domain_api": False,
    }
    body.update(overrides)
    return body


def _create_temporary_customer(client, **overrides):
    payload = assert_success(
        client.post(CUSTOMERS_URL, json=_customer_body(**overrides)),
        "创建 License 临时客户",
    )
    customer = payload["data"]
    assert isinstance(customer, dict), customer
    assert isinstance(customer.get("id"), int) and customer["id"] > 0, customer
    assert customer.get("name", "").startswith("AT-License客户-"), customer
    assert customer.get("app_id"), customer
    assert customer.get("app_secret"), customer
    assert customer.get("valid_end"), customer
    return customer


def _cleanup_temporary_customer(client, customer_id):
    if not customer_id:
        return
    try:
        client.delete("%s/%s" % (CUSTOMERS_URL, customer_id))
    except Exception:
        pass


def _assert_code(response, action, expected_code):
    payload = parse_json(response, action)
    assert response.status_code == 200, "%s HTTP 状态异常：%s" % (action, response.text)
    assert payload.get("code") == expected_code, "%s 业务码不正确：%s" % (action, payload)
    return payload


@pytest.fixture(scope="module")
def license_client():
    return management_client()


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-License")
class TestLicenseAccessAndValidation:
    """License 接口的鉴权、生成、下载和验签契约。"""

    @allure.feature("访问权限")
    def test_License受保护接口_未登录访问被拒绝(self):
        anonymous_client = HttpClient(headers=default_headers.copy())
        assert_auth_required(
            anonymous_client.post(
                LICENSE_URL + "/generate",
                params={
                    "customer_id": 2147483647,
                    "app_id": "anonymous",
                    "secret": "anonymous",
                    "expire_date": "2027-09-18T00:00:00",
                },
            ),
            "匿名生成客户 License",
        )
        assert_auth_required(
            anonymous_client.get(LICENSE_URL + "/download", params={"customer_id": 2147483647}),
            "匿名下载客户 License",
        )
        assert_auth_required(
            anonymous_client.post(CUSTOMER_SYNC_URL, json={"customer_id": 2147483647}),
            "匿名同步客户 License",
        )

    @allure.feature("参数校验")
    def test_License接口_缺少必填参数返回参数错误(self, license_client):
        assert_validation_error(
            license_client.post(LICENSE_URL + "/generate"),
            "生成 License 缺少查询参数",
            (
                ("query", "customer_id"),
                ("query", "app_id"),
                ("query", "secret"),
                ("query", "expire_date"),
            ),
        )
        assert_validation_error(
            license_client.get(LICENSE_URL + "/download"),
            "下载 License 缺少客户 ID",
            (("query", "customer_id"),),
        )
        assert_validation_error(
            license_client.post(CUSTOMER_SYNC_URL, json={}),
            "同步 License 缺少客户 ID",
            (("body", "customer_id"),),
        )

    @allure.feature("License 验签")
    def test_客户License下载后_验证接口返回签名载荷(self, license_client):
        _require_write_tests()
        customer_id = None
        try:
            customer = _create_temporary_customer(license_client)
            customer_id = customer["id"]

            download_payload = assert_success(
                license_client.get(
                    LICENSE_URL + "/download",
                    params={"customer_id": customer_id},
                ),
                "下载客户 License",
            )
            download_data = download_payload["data"]
            assert download_data.get("customer_name") == customer["name"], download_data
            license_content = download_data.get("license")
            assert isinstance(license_content, str) and license_content, download_data

            verify_payload = assert_success(
                license_client.post(
                    LICENSE_URL + "/verify",
                    params={"license": license_content},
                ),
                "验证下载的客户 License",
            )
            verify_data = verify_payload["data"]
            assert verify_data.get("app_id") == customer["app_id"], verify_data
            assert verify_data.get("secret") == customer["app_secret"], verify_data
            assert verify_data.get("pos_count") == customer["pos_count"], verify_data
            assert verify_data.get("dining_limit") == customer["dining_limit"], verify_data
            assert verify_data.get("expire_date"), verify_data
        finally:
            _cleanup_temporary_customer(license_client, customer_id)

    @allure.feature("License 无效校验")
    def test_非法License_返回统一错误码(self, license_client):
        response = license_client.post(
            LICENSE_URL + "/verify",
            params={"license": '{"payload":"invalid","signature":"invalid"}'},
        )
        assert_client_error(
            response,
            "验证非法 License",
            code=LICENSE_INVALID_CODE,
            msg="无效的license",
            data_type=(dict, list, type(None)),
        )

    @allure.feature("License 生成")
    def test_客户License生成_返回下载地址和可验证内容(self, license_client):
        """固定生成接口应与 LicenseUtils 的完整参数保持一致。"""
        _require_write_tests()
        customer_id = None
        try:
            customer = _create_temporary_customer(license_client)
            customer_id = customer["id"]
            response = license_client.post(
                LICENSE_URL + "/generate",
                params={
                    "customer_id": customer_id,
                    "app_id": customer["app_id"],
                    "secret": customer["app_secret"],
                    "expire_date": "%sT00:00:00" % customer["valid_end"],
                },
            )
            payload = assert_success(response, "生成客户 License")
            data = payload["data"]
            assert isinstance(data.get("license"), str) and data["license"], data
            assert data.get("download_url") == (
                "%s/download?customer_id=%s" % (LICENSE_URL, customer_id)
            ), data
        finally:
            _cleanup_temporary_customer(license_client, customer_id)


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-销售管理-License")
class TestCustomerLicenseQueryAndSync:
    """客户 License 查询、校验和远端同步边界。"""

    @allure.feature("客户 License 查询")
    def test_客户License查询与校验_返回标准成功响应(self, license_client):
        """客户级入口不能只声明路由而不返回业务结果。"""
        _require_write_tests()
        customer_id = None
        try:
            customer = _create_temporary_customer(license_client)
            customer_id = customer["id"]

            get_response = license_client.get("%s/license/%s" % (LICENSE_URL, customer_id))
            get_payload = assert_success(get_response, "获取客户 License 信息")
            get_data = get_payload["data"]
            assert isinstance(get_data, dict) and get_data.get("license"), get_payload
            assert get_data.get("customer_name") == customer["name"], get_data

            validate_response = license_client.post(
                "%s/license/%s/validate" % (LICENSE_URL, customer_id)
            )
            validate_payload = assert_success(validate_response, "校验客户 License")
            validate_data = validate_payload["data"]
            assert isinstance(validate_data, dict), validate_payload
            assert validate_data.get("valid") is True, validate_data
        finally:
            _cleanup_temporary_customer(license_client, customer_id)

    @allure.feature("客户不存在")
    def test_客户License查询_不存在客户返回客户不存在(self, license_client):
        get_response = license_client.get("%s/license/%s" % (LICENSE_URL, 2147483647))
        _assert_code(get_response, "获取不存在客户 License", CUSTOMER_NOT_FOUND_CODE)

        validate_response = license_client.post(
            "%s/license/%s/validate" % (LICENSE_URL, 2147483647)
        )
        _assert_code(validate_response, "校验不存在客户 License", CUSTOMER_NOT_FOUND_CODE)

    @allure.feature("客户不存在")
    def test_客户License同步_不存在客户返回客户不存在(self, license_client):
        sync_response = license_client.post(
            CUSTOMER_SYNC_URL,
            json={"customer_id": 2147483647},
        )
        _assert_code(sync_response, "同步不存在客户 License", CUSTOMER_NOT_FOUND_CODE)

    @allure.feature("客户域名")
    def test_客户License同步_缺少域名返回域名缺失(self, license_client):
        _require_write_tests()
        customer_id = None
        try:
            customer = _create_temporary_customer(license_client)
            customer_id = customer["id"]
            response = license_client.post(
                CUSTOMER_SYNC_URL,
                json={"customer_id": customer_id},
            )
            assert_client_error(
                response,
                "同步无域名客户 License",
                code=CUSTOMER_DOMAIN_MISSING_CODE,
                msg="客户缺少域名信息",
                data_type=(dict, list, type(None)),
            )
        finally:
            _cleanup_temporary_customer(license_client, customer_id)

    @allure.feature("远端同步失败")
    def test_客户License同步_远端拒绝或不可达返回操作失败(self, license_client):
        _require_write_tests()
        customer_id = None
        try:
            customer = _create_temporary_customer(
                license_client,
                domain_name="http://127.0.0.1:1",
            )
            customer_id = customer["id"]
            response = license_client.post(
                CUSTOMER_SYNC_URL,
                json={"customer_id": customer_id},
            )
            payload = _assert_code(response, "同步到不可达客户域名", OPERATION_FAILED_CODE)
            assert payload.get("msg", "").startswith("同步请求失败：无法连接到目标服务器"), payload
            assert payload.get("data") in (None, {}, []), payload
        finally:
            _cleanup_temporary_customer(license_client, customer_id)
