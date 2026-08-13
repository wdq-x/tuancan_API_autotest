# -*- coding: utf-8 -*-
"""License API validation and authorization boundary tests."""
import allure
import pytest

from config.project_information import default_headers
from utils.api_test_support import assert_auth_required, assert_client_error, assert_validation_error, management_client
from utils.http_client import HttpClient


@pytest.fixture(scope="module")
def license_client():
    return management_client()


@allure.parent_suite("API regression")
@allure.suite("Management platform - license")
class TestLicenseManagement:
    @allure.feature("Authorization")
    def test_anonymous_license_generation_and_download_are_rejected(self):
        client = HttpClient(headers=default_headers.copy())
        assert_auth_required(client.post("/license/generate"), "anonymous license generation")
        assert_auth_required(client.get("/license/download", params={"customer_id": 2147483647}), "anonymous license download")

    @allure.feature("Validation")
    def test_license_verify_and_generation_validation_contracts(self, license_client):
        assert_client_error(
            HttpClient().post("/license/verify", params={"license": "not-a-license"}),
            "verify malformed license",
            code=5304,
            msg="无效的license",
            data_type=type(None),
        )
        assert_validation_error(
            license_client.post("/license/generate"),
            "generate license without required fields",
            (("query", "customer_id"), ("query", "app_id"), ("query", "secret"), ("query", "expire_date")),
        )
