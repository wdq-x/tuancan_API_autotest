# -*- coding: utf-8 -*-
"""Public distributor refund amount and receipt confirmation API tests."""
import requests

import allure

from utils.api_test_support import assert_client_error, assert_success, assert_validation_error
from utils.http_client import NO_PROXIES, HttpClient


ACCOUNT_URL = "/v1/distributor-refund-confirm"
RECEIPT_URL = "/v1/distributor-refund-receipt"


def _refund_confirmation_payload(**overrides):
    payload = {
        "company_name": "AT-unknown-company",
        "account_name": "AT account",
        "bank_name": "AT bank",
        "account_number": "622200001234",
        "confirmer_name": "API tester",
        "confirmer_phone": "13800138000",
        "signature": "data:image/png;base64,abcdefghijklmnop",
    }
    payload.update(overrides)
    return payload


def _receipt_confirmation_payload(**overrides):
    payload = {
        "company_name": "AT-unknown-company",
        "account_last4": "1234",
        "confirmer_name": "API tester",
        "confirmer_phone": "13800138000",
        "signature": "data:image/png;base64,abcdefghijklmnop",
    }
    payload.update(overrides)
    return payload


@allure.parent_suite("API regression")
@allure.suite("Public distributor refund confirmation")
class TestDistributorRefundAmountConfirmation:
    @allure.feature("Pages and administration")
    def test_refund_pages_and_admin_read_models_are_available(self):
        client = HttpClient()
        for suffix, action in (("/h5", "load refund H5"), ("/admin", "load refund administration page")):
            response = client.get(ACCOUNT_URL + suffix)
            assert response.status_code == 200, "%s failed: %s" % (action, response.text[:500])
            assert "text/html" in response.headers.get("Content-Type", ""), response.headers

        for suffix, action in (
            ("/admin/summary", "get refund summary"),
            ("/admin/accounts", "list refund accounts"),
            ("/admin/pending", "list pending refund confirmations"),
            ("/admin/confirmations", "list refund confirmations"),
            ("/admin/modifications", "list refund modifications"),
        ):
            payload = assert_success(client.get(ACCOUNT_URL + suffix), action)
            assert payload.get("data") is not None, payload

    @allure.feature("Lookup and confirmation validation")
    def test_unknown_refund_lookup_and_invalid_confirmation_are_rejected(self):
        client = HttpClient()
        assert_client_error(
            client.get(ACCOUNT_URL + "/lookup", params={"name": "AT-unknown-company", "account_last4": "0000"}),
            "look up an unknown refund account",
            code=40401,
            msg="公司名称或银行账号后4位不正确，请核对后重试",
            data_type=type(None),
        )
        assert_validation_error(
            client.post(ACCOUNT_URL + "/confirm", json={}),
            "confirm a refund without required fields",
            (("body", "company_name"), ("body", "signature")),
        )

    @allure.feature("Lookup and confirmation validation")
    def test_refund_lookup_and_confirmation_reject_invalid_format_with_exact_codes(self):
        client = HttpClient()
        assert_validation_error(
            client.get(ACCOUNT_URL + "/lookup", params={"name": "AT-unknown-company", "account_last4": "123"}),
            "look up refund account with a short suffix",
            (("query", "account_last4"),),
        )
        assert_client_error(
            client.get(ACCOUNT_URL + "/lookup", params={"name": "AT-unknown-company", "account_last4": "12a4"}),
            "look up refund account with a non-digit suffix",
            code=40401,
            msg="请输入银行账号后4位数字",
            data_type=type(None),
        )
        assert_client_error(
            client.post(ACCOUNT_URL + "/confirm", json=_refund_confirmation_payload(confirmer_phone="1380013800x")),
            "confirm refund with an invalid phone",
            code=40402,
            msg="请输入正确的11位手机号",
            data_type=type(None),
        )
        assert_client_error(
            client.post(ACCOUNT_URL + "/confirm", json=_refund_confirmation_payload(signature="invalid-signature-data-too-long")),
            "confirm refund with an invalid signature prefix",
            code=40403,
            msg="签字数据无效，请重新签字",
            data_type=type(None),
        )


@allure.parent_suite("API regression")
@allure.suite("Public distributor refund receipt confirmation")
class TestDistributorRefundReceiptConfirmation:
    @allure.feature("Pages and administration")
    def test_receipt_pages_and_admin_read_models_are_available(self):
        client = HttpClient()
        for suffix, action in (("/h5", "load receipt H5"), ("/upload", "load receipt upload page"), ("/admin", "load receipt administration page")):
            response = client.get(RECEIPT_URL + suffix)
            assert response.status_code == 200, "%s failed: %s" % (action, response.text[:500])
            assert "text/html" in response.headers.get("Content-Type", ""), response.headers

        for suffix, action in (
            ("/admin/summary", "get receipt summary"),
            ("/admin/accounts", "list receipt account options"),
            ("/admin/receipts", "list uploaded receipts"),
            ("/admin/pending", "list pending receipt confirmations"),
            ("/admin/no-receipt", "list accounts without receipts"),
            ("/admin/confirmations", "list receipt confirmations"),
        ):
            payload = assert_success(client.get(RECEIPT_URL + suffix), action)
            assert payload.get("data") is not None, payload

    @allure.feature("Lookup and upload validation")
    def test_unknown_receipt_lookup_empty_confirmation_and_empty_upload_are_rejected(self):
        client = HttpClient()
        assert_client_error(
            client.get(RECEIPT_URL + "/lookup", params={"name": "AT-unknown-company", "account_last4": "0000"}),
            "look up an unknown receipt account",
            code=40401,
            msg="公司名称或银行账号后4位不正确，请核对后重试",
            data_type=type(None),
        )
        assert_validation_error(
            client.post(RECEIPT_URL + "/confirm", json={}),
            "confirm a receipt without required fields",
            (("body", "company_name"), ("body", "signature")),
        )
        assert_validation_error(
            client.post(RECEIPT_URL + "/receipt/upload", json={}),
            "upload a receipt without a file",
            (("body", "company_name"), ("body", "file")),
        )

    @allure.feature("Lookup, upload, and confirmation validation")
    def test_receipt_validation_and_unknown_file_contracts_are_exact(self):
        client = HttpClient()
        assert_validation_error(
            client.get(RECEIPT_URL + "/lookup", params={"name": "AT-unknown-company", "account_last4": "123"}),
            "look up receipt with a short suffix",
            (("query", "account_last4"),),
        )
        assert_client_error(
            client.get(RECEIPT_URL + "/lookup", params={"name": "AT-unknown-company", "account_last4": "12a4"}),
            "look up receipt with a non-digit suffix",
            code=40401,
            msg="请输入银行账号后4位数字",
            data_type=type(None),
        )
        assert_client_error(
            client.post(RECEIPT_URL + "/confirm", json=_receipt_confirmation_payload(confirmer_phone="1380013800x")),
            "confirm receipt with an invalid phone",
            code=40403,
            msg="请输入正确的11位手机号",
            data_type=type(None),
        )
        assert_client_error(
            client.post(RECEIPT_URL + "/confirm", json=_receipt_confirmation_payload(signature="invalid-signature-data-too-long")),
            "confirm receipt with an invalid signature prefix",
            code=40404,
            msg="签字数据无效，请重新签字",
            data_type=type(None),
        )
        assert_client_error(
            client.get(RECEIPT_URL + "/receipt/file/2147483647"),
            "download an unknown receipt file",
            code=4040,
            msg="回执单不存在",
            data_type=type(None),
        )

    @allure.feature("Receipt upload validation")
    def test_receipt_upload_rejects_missing_filename_without_writing_data(self):
        client = HttpClient()
        response = requests.post(
            client._url(RECEIPT_URL + "/receipt/upload"),
            data={"company_name": "AT-unknown-company"},
            files={"file": ("", b"placeholder", "application/pdf")},
            headers={"Accept": "application/json"},
            timeout=client.timeout,
            proxies=NO_PROXIES,
        )
        assert_client_error(
            response,
            "upload a receipt without a filename",
            code=40410,
            msg="请选择回执单文件",
            data_type=type(None),
        )
