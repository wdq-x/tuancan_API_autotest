# -*- encoding=utf8 -*-
"""
接口自动化测试项目配置
- 环境 base_url、请求头、超时等
- Allure 报告环境变量
"""
import os

try:
    from config.local_test_accounts import LOCAL_TEST_ACCOUNT
except ImportError:
    # 本地凭据文件被 .gitignore 忽略；CI 仅使用 GitHub Secrets 注入的环境变量。
    LOCAL_TEST_ACCOUNT = {}

# Allure 报告环境信息（用于 report/widgets/environment.json）
ENV_VARS = {
    "report_title": "接口自动化测试报告",
    "project_name": "团餐云平台接口自动化测试",
    "tester": "Administrator",
    "department": "小吴",
}

# 默认请求头（按需修改）
default_headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# 请求超时时间（秒）
timeout = 10

# 接口测试环境 base_url。CI 可通过 API_BASE_URL 覆盖默认测试环境。
# 线上环境
base_url = os.getenv("API_BASE_URL", "https://sa-demo-cloud.holderzone.cn").rstrip("/")
# # 本地
# base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:7777").rstrip("/")

def _account_from_environment():
    """优先读取 CI 环境变量；本地无环境变量时使用被忽略的本地配置。"""
    username = os.getenv("MANAGEMENT_TEST_USERNAME", "").strip()
    password = os.getenv("MANAGEMENT_TEST_PASSWORD", "").strip()
    if username and password:
        return {"username": username, "password": password}
    return {
        "username": str(LOCAL_TEST_ACCOUNT.get("username") or "").strip(),
        "password": str(LOCAL_TEST_ACCOUNT.get("password") or "").strip(),
    }


# CI 通过 GitHub Secrets 注入 MANAGEMENT_TEST_*；本地运行则使用 local_test_accounts.py。
MANAGEMENT_TEST_ACCOUNT = _account_from_environment()

# 移动端与管理平台统一使用同一套账号，不维护额外的移动端 CI 凭据。
MOBILE_TEST_ACCOUNT = MANAGEMENT_TEST_ACCOUNT

# 渠道管理和线索管理的写操作用例会创建带 AT- 前缀的临时数据，并在用例结束时清理。
# 默认启用完整业务链路回归；CI 可显式设为 true/false。
ENABLE_WRITE_TESTS = os.getenv("ENABLE_WRITE_TESTS", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
