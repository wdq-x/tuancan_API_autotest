# -*- encoding=utf8 -*-
"""
接口自动化测试运行入口
- 使用 pytest 执行用例并生成 Allure 结果
- 生成并打开 Allure HTML 报告
"""
import json
import os
import pytest

from utils.tools import report_dir
from utils.report_optimize import set_report_env_on_html, set_report_name
from config.project_information import ENV_VARS

# 项目根目录（run.py 所在目录）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# 报告 HTML 输出目录
REPORT_HTML_DIR = os.path.join(PROJECT_ROOT, "report", "allure_html")

# 报告输出目录
report_html_path = "report/allure_html"

'''''''''''''''''''''''''''''要执行的测试用例（可改为具体用例文件或目录）'''''''''''''''''''''''''''''''''''''''
case_list = r'E:\jiekou\test_case\test_02_api_order.py'


def _path_for_shell(path):
    """将路径转为 shell 可用的格式，避免 Windows 下反斜杠被当作转义（如 \\r -> 回车）"""
    return os.path.normpath(path).replace("\\", "/")


def _strip_title_path_from_allure_results(report_path):
    """
    从 Allure 结果 JSON 中移除 titlePath 字段，使旧版 Allure CLI 能解析。
    不修改包版本时的兼容方案。
    """
    if not os.path.isdir(report_path):
        return
    for name in os.listdir(report_path):
        if not name.endswith("-result.json"):
            continue
        path = os.path.join(report_path, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "titlePath" in data:
                del data["titlePath"]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, OSError):
            pass


if __name__ == "__main__":
    # 切换到项目根目录，保证相对路径与 allure 结果路径一致
    os.chdir(PROJECT_ROOT)
    # 基于项目根目录生成结果路径，避免因运行目录不同导致报告为空
    report_path = report_dir(PROJECT_ROOT)
    os.makedirs(report_path, exist_ok=True)
    pytest.main(["-s", "-q", case_list, "--alluredir", report_path])

    # 检查是否有结果文件（便于排查“报告无数据”）
    result_files = [f for f in os.listdir(report_path) if f.endswith((".json", ".json.gz"))]
    if not result_files:
        print("警告: 结果目录为空，请检查 pytest 是否执行成功。路径: %s" % report_path)

    # 移除 titlePath，兼容旧版 Allure CLI（不修改包版本）
    _strip_title_path_from_allure_results(report_path)

    # Windows 下路径中的 \ 在 os.system 字符串里可能被当作转义，改为正斜杠传给 shell
    report_path_shell = _path_for_shell(report_path)
    html_dir_shell = _path_for_shell(REPORT_HTML_DIR)
    os.system('allure generate "%s" -o "%s" --clean' % (report_path_shell, html_dir_shell))
    set_report_env_on_html(ENV_VARS, allure_html_path=REPORT_HTML_DIR)
    set_report_name(allure_html_path=REPORT_HTML_DIR, new_name="接口自动化测试报告")
    os.system('allure open "%s"' % html_dir_shell)
