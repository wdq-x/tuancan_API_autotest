# -*- encoding=utf8 -*-
"""
接口自动化测试项目配置
- 环境 base_url、请求头、超时等
- Allure 报告环境变量
"""

# Allure 报告环境信息（用于 report/widgets/environment.json）
ENV_VARS = {
    "report_title": "接口自动化测试报告",
    "project_name": "团餐云平台接口自动化测试",
    "tester": "Administrator",
    "department": "小吴",
}

# 接口测试环境 base_url（按需修改为实际被测系统地址）
base_url = "http://localhost:3001"

# 默认请求头（按需修改）
default_headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# 请求超时时间（秒）
timeout = 10

# 管理平台接口自动化唯一测试账号。渠道、线索、客户及后续所有管理平台模块
# 都直接读取此对象登录；只在这里维护一次账号密码。
MANAGEMENT_TEST_ACCOUNT = {
    "username": "17303457961",
    "password": "12345678",
}

# 渠道管理和线索管理的写操作用例会创建带 AT- 前缀的临时数据，并在用例结束时清理。
# 当前 base_url 指向本地测试平台，默认启用完整业务链路回归。
ENABLE_WRITE_TESTS = True
