# -*- encoding=utf8 -*-
"""
接口自动化测试项目配置
- 环境 base_url、请求头、超时等
- Allure 报告环境变量
"""
import os

# Allure 报告环境信息（用于 report/widgets/environment.json）
ENV_VARS = {
    "report_title": "接口自动化测试报告",
    "project_name": "团餐云平台接口自动化测试",
    "tester": "Administrator",
    "department": "小吴",
}

# 接口测试环境 base_url。CI 可通过 API_BASE_URL 覆盖默认测试环境。
base_url = os.getenv("API_BASE_URL", "https://sa-demo-cloud.holderzone.cn").rstrip("/")

# 默认请求头（按需修改）
default_headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# 请求超时时间（秒）
timeout = 10

# 管理平台接口自动化唯一测试账号。凭据只从环境变量读取，避免提交到仓库。
MANAGEMENT_TEST_ACCOUNT = {
    "username": os.getenv("MANAGEMENT_TEST_USERNAME", ""),
    "password": os.getenv("MANAGEMENT_TEST_PASSWORD", ""),
}

# 渠道管理和线索管理的写操作用例会创建带 AT- 前缀的临时数据，并在用例结束时清理。
# 默认启用完整业务链路回归；CI 可显式设为 true/false。
ENABLE_WRITE_TESTS = os.getenv("ENABLE_WRITE_TESTS", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
