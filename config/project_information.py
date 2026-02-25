# -*- encoding=utf8 -*-
"""
接口自动化测试项目配置
- 环境 base_url、请求头、超时等
- Allure 报告环境变量
"""

# Allure 报告环境信息（用于 report/widgets/environment.json）
ENV_VARS = {
    "report_title": "接口自动化测试报告",
    "project_name": "团餐接口自动化测试",
    "tester": "Administrator",
    "department": "小吴",
}

# 接口测试环境 base_url（按需修改为实际被测系统地址）
base_url = "https://jicai-group.holderzone.cn"

# 默认请求头（按需修改）
default_headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# 请求超时时间（秒）
timeout = 10
