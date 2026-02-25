# -*- encoding=utf8 -*-
"""
工具函数：报告路径等
"""
import os
import time


def report_dir(base_dir=None):
    """
    生成带日期+时间的 Allure 结果目录路径，每次运行独立目录。
    base_dir: 项目根目录，若传入则返回绝对路径；否则返回相对路径 ./report/allure_result/日期_时间
    """
    date_time = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(time.time()))
    if base_dir:
        return os.path.join(base_dir, "report", "allure_result", date_time)
    return os.path.join(".", "report", "allure_result", date_time)
