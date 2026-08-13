# -*- coding: utf-8 -*-
"""Mobile home business-summary API regression tests."""
import allure
import pytest

from config.project_information import default_headers
from utils.api_test_support import assert_auth_required, assert_success, assert_validation_error, management_client
from utils.http_client import HttpClient


URL = "/v1/mobile/home/business-summary"


@pytest.fixture(scope="module")
def mobile_home_client():
    return management_client(client_type="mobile")


@allure.parent_suite("API regression")
@allure.suite("Mobile - home")
class TestMobileHomeBusinessSummary:
    @allure.feature("Access control")
    def test_anonymous_business_summary_is_rejected(self):
        assert_auth_required(HttpClient(headers=default_headers.copy()).get(URL), "anonymous mobile home business summary")

    @allure.feature("Business summary")
    def test_business_summary_returns_data_and_validates_day_range(self, mobile_home_client):
        payload = assert_success(mobile_home_client.get(URL, params={"days": 15}), "get mobile home business summary")
        assert isinstance(payload.get("data"), dict), payload
        assert_validation_error(
            mobile_home_client.get(URL, params={"days": 0}),
            "get mobile home summary with invalid days",
            (("query", "days"),),
        )
