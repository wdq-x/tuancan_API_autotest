# -*- encoding=utf8 -*-
"""
Allure 报告优化：环境信息、报告标题
"""
import json
import os


def set_report_env_on_html(env_info: dict, allure_html_path: str = None):
    """
    在 allure-html 报告的 widgets/environment.json 中写入环境信息
    allure_html_path: 报告目录，默认 ./report/allure_html（相对当前工作目录）
    """
    envs = []
    for k, v in env_info.items():
        envs.append({"name": k, "values": [v]})
    base = allure_html_path if allure_html_path else os.path.join(".", "report", "allure_html")
    path = os.path.join(base, "widgets", "environment.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envs, f, ensure_ascii=False, indent=4)


def set_report_name(allure_html_path: str, new_name: str):
    """
    修改 Allure 报告 Overview 的标题文案（summary.json 中的 reportName）
    """
    title_filepath = os.path.join(allure_html_path, "widgets", "summary.json")
    if not os.path.exists(title_filepath):
        return
    with open(title_filepath, "rb") as f:
        params = json.load(f)
    params["reportName"] = new_name
    with open(title_filepath, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=4)
