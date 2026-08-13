# -*- coding: utf-8 -*-
"""Device heartbeat, overview, and version-management API regression tests."""
import allure
import pytest

from config.project_information import default_headers
from utils.api_test_support import assert_auth_required, assert_client_error, assert_success, assert_validation_error, management_client, page_items
from utils.http_client import HttpClient


OVERVIEW_URL = "/v1/device-overview"
VERSIONS_URL = "/v1/device-versions"
HEARTBEAT_URL = "/v1/device-heartbeats"


def _heartbeat_payload(**overrides):
    payload = {
        "service_id": "AT-device-service",
        "device_sn": "AT-device-sn",
        "event_type": "heartbeat",
        "report_source": "app_sdk",
    }
    payload.update(overrides)
    return payload


@pytest.fixture(scope="module")
def device_client():
    return management_client()


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与运维-设备管理")
class Test设备心跳校验:
    @allure.feature("心跳校验")
    @allure.title("设备心跳批量空请求被拒绝")
    def test_device_heartbeat_batch_rejects_an_empty_payload(self):
        response = HttpClient(headers=default_headers.copy()).post(HEARTBEAT_URL + "/batch", json={})
        assert_client_error(
            response,
            "submit an empty device heartbeat batch",
            code=5801,
            msg="service_id 不能为空",
            data_type=type(None),
        )

    @allure.feature("心跳校验")
    @allure.title("设备心跳批量缺少或非法项目被拒绝")
    def test_device_heartbeat_batch_rejects_missing_or_invalid_items(self):
        client = HttpClient(headers=default_headers.copy())
        for payload, action, message in (
            ({"service_id": "AT-device-service"}, "submit a batch without items", "items 不能为空"),
            ({"service_id": "AT-device-service", "items": "not-a-list"}, "submit a batch with a non-list items value", "items 不能为空"),
            ({"service_id": "AT-device-service", "items": [None]}, "submit a batch with a non-object item", "items 只能包含对象"),
        ):
            assert_client_error(
                client.post(HEARTBEAT_URL + "/batch", json=payload),
                action,
                code=5801,
                msg=message,
                data_type=type(None),
            )


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与运维-设备管理")
class Test设备概览与版本管理:
    @allure.feature("访问控制")
    @allure.title("未登录访问设备概览被拒绝")
    def test_anonymous_device_overview_is_rejected(self):
        assert_auth_required(HttpClient(headers=default_headers.copy()).get(OVERVIEW_URL), "anonymous device overview")

    @allure.feature("设备概览")
    @allure.title("设备列表阈值与版本概览查询")
    def test_device_lists_thresholds_and_version_views_have_stable_envelopes(self, device_client):
        overview = assert_success(
            device_client.get(OVERVIEW_URL, params={"page": 1, "page_size": 10}),
            "list devices",
            "device overview permission is not assigned to the test account",
        )
        assert isinstance(overview.get("data"), dict), overview
        assert isinstance(list(page_items(overview)), list), overview

        thresholds = assert_success(device_client.get("%s/thresholds" % OVERVIEW_URL), "get device thresholds")
        assert isinstance(thresholds.get("data"), (dict, list)), thresholds

        versions = assert_success(device_client.get("%s/versions" % OVERVIEW_URL), "get overview version aggregation")
        assert isinstance(versions.get("data"), (dict, list)), versions

        page = device_client.get("%s/versions-page" % OVERVIEW_URL)
        assert page.status_code == 200, page.text[:500]
        assert "text/html" in page.headers.get("Content-Type", ""), page.headers

    @allure.feature("版本管理")
    @allure.title("设备版本目录与更新接口查询")
    def test_device_version_catalogue_and_update_endpoints_are_readable(self, device_client):
        version_list = assert_success(
            device_client.get(VERSIONS_URL, params={"page": 1, "page_size": 10}),
            "list device versions",
            "device version permission is not assigned to the test account",
        )
        assert isinstance(version_list.get("data"), (dict, list)), version_list

        for path, action in (
            ("%s/service-options" % VERSIONS_URL, "get device version service options"),
            ("%s/app-packages" % VERSIONS_URL, "list device application packages"),
            ("%s/latest-apps" % VERSIONS_URL, "get latest applications"),
            ("%s/logs/recent" % VERSIONS_URL, "get recent device version logs"),
        ):
            payload = assert_success(device_client.get(path), action)
            assert payload.get("data") is not None, payload

    @allure.feature("版本管理")
    @allure.title("设备版本创建参数校验")
    def test_device_version_creation_requires_a_valid_payload(self, device_client):
        assert_validation_error(
            device_client.post(VERSIONS_URL, json={}),
            "create a device version without required fields",
            (("body", "service_id"),),
        )

    @allure.feature("版本管理")
    @allure.title("未知设备版本和应用包异常契约")
    def test_device_version_and_package_not_found_contracts_are_exact(self, device_client):
        unknown_id = 2147483647
        for request, action in (
            (device_client.get("%s/%s" % (VERSIONS_URL, unknown_id)), "get an unknown device version"),
            (device_client.put("%s/%s" % (VERSIONS_URL, unknown_id), json={"publish_status": "draft"}), "update an unknown device version"),
            (device_client.delete("%s/%s" % (VERSIONS_URL, unknown_id)), "delete an unknown device version"),
        ):
            assert_client_error(
                request,
                action,
                code=5708,
                msg="版本记录不存在",
                data_type=type(None),
            )
        assert_client_error(
            device_client.get("%s/app-packages/%s/versions" % (VERSIONS_URL, unknown_id)),
            "get versions for an unknown app package",
            code=5713,
            msg="应用包不存在",
            data_type=type(None),
        )
        assert_client_error(
            device_client.delete("%s/app-package-versions/%s" % (VERSIONS_URL, unknown_id)),
            "delete an unknown app package version",
            code=5714,
            msg="应用包版本不存在",
            data_type=type(None),
        )

    @allure.feature("设备概览")
    @allure.title("未知设备与非法分页请求被拒绝")
    def test_device_overview_rejects_unknown_device_and_invalid_page(self, device_client):
        assert_validation_error(
            device_client.get(OVERVIEW_URL, params={"page": 0}),
            "list device overview with an invalid page",
            (("query", "page"),),
        )
        for request, action in (
            (device_client.get(OVERVIEW_URL + "/AT-device-service/AT-device-sn"), "get an unknown device"),
            (
                device_client.post(
                    OVERVIEW_URL + "/AT-device-service/AT-device-sn/profile",
                    json={"device_alias": "AT alias"},
                ),
                "save a profile for an unknown device",
            ),
        ):
            assert_client_error(
                request,
                action,
                code=5701,
                msg="设备不存在",
                data_type=type(None),
            )
