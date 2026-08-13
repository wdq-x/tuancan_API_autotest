# -*- coding: utf-8 -*-
"""Document-management API regression tests, including a cleaned-up file lifecycle."""
from uuid import uuid4

import allure
import pytest
import requests

from config.project_information import ENABLE_WRITE_TESTS, default_headers
from utils.api_test_support import assert_auth_required, assert_client_error, assert_success, assert_validation_error, management_client
from utils.http_client import NO_PROXIES, HttpClient


BASE_URL = "/v1/document-management"


@pytest.fixture(scope="module")
def document_client():
    return management_client()


def _multipart_headers(client):
    return {key: value for key, value in client.headers.items() if key.lower() != "content-type"}


@allure.parent_suite("API regression")
@allure.suite("Management platform - document management")
class TestDocumentManagementReadModels:
    @allure.feature("Access control")
    def test_anonymous_folder_tree_is_rejected(self):
        assert_auth_required(HttpClient(headers=default_headers.copy()).get(BASE_URL + "/folders/tree"), "anonymous document folder tree")

    @allure.feature("Folder and document views")
    def test_document_read_models_and_unknown_resource_contracts(self, document_client):
        tree = assert_success(document_client.get(BASE_URL + "/folders/tree"), "get document folder tree")
        assert isinstance((tree.get("data") or {}).get("items"), list), tree

        for suffix, action in (
            ("/documents", "list documents"),
            ("/recycle-bin", "list document recycle bin"),
        ):
            payload = assert_success(document_client.get(BASE_URL + suffix, params={"page": 1, "page_size": 10}), action)
            assert isinstance((payload.get("data") or {}).get("items"), list), payload

        assert_client_error(
            document_client.get(BASE_URL + "/documents/2147483647"),
            "get an unknown document",
            code=409105,
            msg="文档不存在",
            data_type=type(None),
        )
        assert_validation_error(
            document_client.post(BASE_URL + "/folders", json={}),
            "create an empty document folder",
            (("body", "name"),),
        )

    @allure.feature("Folder and document validation")
    def test_folder_validation_and_unknown_folder_contracts_are_exact(self, document_client):
        unknown_id = 2147483647
        assert_client_error(
            document_client.post(BASE_URL + "/folders", json={"name": "   "}),
            "create a blank document folder",
            code=4100,
            msg="文件夹名称不能为空",
            data_type=type(None),
        )
        for request, action in (
            (document_client.patch(BASE_URL + "/folders/%s" % unknown_id, json={"name": "AT-folder"}), "update an unknown document folder"),
            (document_client.delete(BASE_URL + "/folders/%s" % unknown_id), "delete an unknown document folder"),
            (
                document_client.patch(
                    BASE_URL + "/folders/%s/move" % unknown_id,
                    json={"parent_id": None, "sibling_ids": [unknown_id]},
                ),
                "move an unknown document folder",
            ),
        ):
            assert_client_error(
                request,
                action,
                code=4040,
                msg="文件夹不存在",
                data_type=type(None),
            )

    @allure.feature("Document and version not-found contracts")
    def test_document_and_version_not_found_contracts_are_exact(self, document_client):
        unknown_id = 2147483647
        document_paths = (
            ("/documents/%s" % unknown_id, "get an unknown document"),
            ("/documents/%s/preview" % unknown_id, "preview an unknown document"),
            ("/documents/%s/download" % unknown_id, "download an unknown document"),
            ("/documents/%s/edit-capability" % unknown_id, "get edit capability for an unknown document"),
            ("/documents/%s/text-content" % unknown_id, "get text content for an unknown document"),
            ("/documents/%s/versions" % unknown_id, "list versions for an unknown document"),
        )
        for suffix, action in document_paths:
            assert_client_error(
                document_client.get(BASE_URL + suffix),
                action,
                code=409105,
                msg="文档不存在",
                data_type=type(None),
            )
        for request, action in (
            (document_client.patch(BASE_URL + "/documents/%s" % unknown_id, json={"name": "AT-file.txt"}), "rename an unknown document"),
            (document_client.delete(BASE_URL + "/documents/%s" % unknown_id), "delete an unknown document"),
            (document_client.post(BASE_URL + "/documents/%s/restore" % unknown_id), "restore an unknown document"),
            (document_client.delete(BASE_URL + "/documents/%s/permanent" % unknown_id), "permanently delete an unknown document"),
        ):
            assert_client_error(
                request,
                action,
                code=409105,
                msg="文档不存在",
                data_type=type(None),
            )
        for suffix, action in (
            ("/versions/%s" % unknown_id, "get an unknown document version"),
            ("/versions/%s/download" % unknown_id, "download an unknown document version"),
            ("/versions/%s/preview" % unknown_id, "preview an unknown document version"),
        ):
            assert_client_error(
                document_client.get(BASE_URL + suffix),
                action,
                code=4040,
                msg="版本不存在",
                data_type=type(None),
            )

    @allure.feature("Pagination and upload validation")
    def test_document_pagination_and_upload_requirements_are_exact(self, document_client):
        assert_validation_error(
            document_client.get(BASE_URL + "/documents", params={"page": 0}),
            "list documents with an invalid page",
            (("query", "page"),),
        )
        assert_validation_error(
            document_client.get(BASE_URL + "/documents", params={"page_size": 101}),
            "list documents with an oversized page",
            (("query", "page_size"),),
        )
        assert_validation_error(
            document_client.get(BASE_URL + "/recycle-bin", params={"page": 0}),
            "list recycle bin with an invalid page",
            (("query", "page"),),
        )
        missing_upload = requests.post(
            document_client._url(BASE_URL + "/documents/upload"),
            data={"folder_id": "2147483647"},
            headers=_multipart_headers(document_client),
            timeout=document_client.timeout,
            proxies=NO_PROXIES,
        )
        assert_validation_error(
            missing_upload,
            "upload a document without a file",
            (("body", "file"),),
        )
        root_upload = requests.post(
            document_client._url(BASE_URL + "/documents/upload"),
            files={"file": ("AT-root-upload.txt", b"no write should occur", "text/plain")},
            headers=_multipart_headers(document_client),
            timeout=document_client.timeout,
            proxies=NO_PROXIES,
        )
        assert_client_error(
            root_upload,
            "upload a document into the root folder",
            code=409202,
            msg="根目录不支持上传文件，请先选择具体文件夹",
            data_type=type(None),
        )


@allure.parent_suite("API regression")
@allure.suite("Management platform - document management")
class TestDocumentManagementLifecycle:
    @allure.feature("Folder and file lifecycle")
    def test_folder_upload_edit_version_recycle_restore_and_permanent_delete(self, document_client):
        if not ENABLE_WRITE_TESTS:
            pytest.skip("write tests are disabled through ENABLE_WRITE_TESTS")

        folder_id = None
        document_id = None
        permanently_deleted = False
        marker = uuid4().hex[:8]
        try:
            folder_payload = assert_success(
                document_client.post(BASE_URL + "/folders", json={"name": "AT-d-%s" % marker}),
                "create temporary document folder",
            )
            folder_id = (folder_payload.get("data") or {}).get("id")
            assert isinstance(folder_id, int) and folder_id > 0, folder_payload

            renamed_payload = assert_success(
                document_client.patch(BASE_URL + "/folders/%s" % folder_id, json={"name": "AT-r-%s" % marker}),
                "rename temporary document folder",
            )
            assert (renamed_payload.get("data") or {}).get("id") == folder_id, renamed_payload

            upload_response = requests.post(
                document_client._url(BASE_URL + "/documents/upload"),
                data={"folder_id": str(folder_id), "version_note": "initial API regression version"},
                files={"file": ("AT-document-%s.txt" % marker, b"document api regression", "text/plain")},
                headers=_multipart_headers(document_client),
                timeout=document_client.timeout,
                proxies=NO_PROXIES,
            )
            upload_payload = assert_success(upload_response, "upload temporary document")
            document_id = (upload_payload.get("data") or {}).get("id")
            assert isinstance(document_id, int) and document_id > 0, upload_payload

            detail = assert_success(document_client.get(BASE_URL + "/documents/%s" % document_id), "get uploaded document")
            assert (detail.get("data") or {}).get("id") == document_id, detail
            capability = assert_success(document_client.get(BASE_URL + "/documents/%s/edit-capability" % document_id), "get document edit capability")
            assert capability.get("data") is not None, capability

            version_response = requests.post(
                document_client._url(BASE_URL + "/documents/%s/versions" % document_id),
                data={"version_note": "second API regression version"},
                files={"file": ("AT-document-%s.txt" % marker, b"document api regression v2", "text/plain")},
                headers=_multipart_headers(document_client),
                timeout=document_client.timeout,
                proxies=NO_PROXIES,
            )
            assert_success(version_response, "save a document version")
            versions = assert_success(document_client.get(BASE_URL + "/documents/%s/versions" % document_id), "list document versions")
            assert len((versions.get("data") or {}).get("items") or []) >= 2, versions

            assert_success(document_client.delete(BASE_URL + "/documents/%s" % document_id), "move document to recycle bin")
            assert_success(document_client.post(BASE_URL + "/documents/%s/restore" % document_id), "restore document from recycle bin")
            assert_success(document_client.delete(BASE_URL + "/documents/%s" % document_id), "move document to recycle bin again")
            assert_success(document_client.delete(BASE_URL + "/documents/%s/permanent" % document_id), "permanently delete document")
            permanently_deleted = True
            document_id = None
        finally:
            if document_id and not permanently_deleted:
                try:
                    document_client.delete(BASE_URL + "/documents/%s" % document_id)
                    document_client.delete(BASE_URL + "/documents/%s/permanent" % document_id)
                except Exception:
                    pass
            if folder_id:
                try:
                    document_client.delete(BASE_URL + "/folders/%s" % folder_id)
                except Exception:
                    pass
