# -*- coding: utf-8 -*-
"""管理平台用户、角色、权限与系统操作日志接口自动化测试。

测试创建唯一的 ``AT-`` 角色和用户，覆盖角色 CRUD、用户 CRUD、角色分配、
角色用户查询及系统日志。用户删除接口是业务设计的软删除，清理时会先撤销角色
关系、删除临时角色，再调用用户删除接口使 AT 用户禁止登录。

权限初始化会根据后端内置配置对全局权限字典执行幂等同步，因此单独校验返回的
计数类型，不假设每个环境的 created / updated 具体数值。
"""
from uuid import uuid4

import allure
import pytest

from config.project_information import ENABLE_WRITE_TESTS
from utils.api_test_support import assert_success, management_client, page_items


ROLES_URL = "/v1/roles"
USERS_URL = "/v1/users"
PERMISSIONS_URL = "/v1/permissions"
SYSTEM_LOGS_URL = "/v1/system-operation-logs"


def _require_write_tests():
    if not ENABLE_WRITE_TESTS:
        pytest.skip("写操作已在 config/project_information.py 中通过 ENABLE_WRITE_TESTS 关闭")


def _page_data(payload, action):
    data = payload.get("data")
    assert isinstance(data, dict), "%s must return a paging object: %s" % (action, payload)
    assert isinstance(data.get("items"), list), "%s must return data.items: %s" % (action, payload)
    assert isinstance(data.get("total"), int) and data["total"] >= 0, "%s total is invalid: %s" % (action, payload)
    assert isinstance(data.get("page"), int) and isinstance(data.get("page_size"), int), "%s paging fields are invalid: %s" % (action, payload)
    return data


def _available_department_id(client):
    payload = assert_success(
        client.get(USERS_URL, params={"page": 1, "page_size": 100, "include_roles": "true"}),
        "list active users for AT user department",
    )
    _page_data(payload, "list active users for AT user department")
    for user in page_items(payload):
        department_id = user.get("department_id") if isinstance(user, dict) else None
        if isinstance(department_id, int) and department_id > 0:
            return department_id
    pytest.skip("当前环境没有带有效 department_id 的活动用户，无法通过用户创建接口构造可回收 AT 用户")


def _cleanup_user_and_role(client, user_id, role_id):
    if user_id:
        try:
            client.put("%s/%s/roles" % (USERS_URL, user_id), json={"role_ids": []})
        except Exception:
            pass
    if role_id:
        try:
            client.delete("%s/%s" % (ROLES_URL, role_id))
        except Exception:
            pass
    if user_id:
        try:
            client.delete("%s/%s" % (USERS_URL, user_id))
        except Exception:
            pass


@allure.parent_suite("接口自动化")
@allure.suite("管理平台-系统与权限-用户角色权限")
class Test用户角色权限:
    @allure.feature("权限字典")
    def test_权限列表与初始化返回分页及同步计数(self):
        client = management_client()
        with allure.step("分页查询权限字典"):
            permissions_payload = assert_success(
                client.get(PERMISSIONS_URL, params={"page": 1, "page_size": 100}),
                "list permissions",
            )
        permission_data = _page_data(permissions_payload, "list permissions")
        assert permission_data["items"], "权限字典为空，无法验证角色权限配置"
        assert all(isinstance(item.get("id"), int) and item.get("code") for item in permission_data["items"]), permission_data

        with allure.step("执行幂等权限初始化"):
            init_payload = assert_success(client.post("%s/init" % PERMISSIONS_URL), "initialize permissions")
        init_data = init_payload.get("data") or {}
        assert isinstance(init_data.get("created"), int) and init_data["created"] >= 0, init_payload
        assert isinstance(init_data.get("updated"), int) and init_data["updated"] >= 0, init_payload
