# -*- encoding=utf8 -*-
"""
HTTP 请求封装：统一 get/post/put/delete，便于接口用例调用
"""
import logging
import sys
import os

# 将项目根目录加入 path，便于引用 config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config.project_information import base_url, default_headers, timeout

logger = logging.getLogger(__name__)


class HttpClient:
    """接口请求客户端：自动拼接 base_url、默认请求头与超时"""

    def __init__(self, base_url_=None, headers=None, timeout_=None):
        self.base_url = base_url_ or base_url
        self.headers = headers if headers is not None else default_headers.copy()
        self.timeout = timeout_ if timeout_ is not None else timeout

    def _url(self, path):
        """拼接完整 URL"""
        path = path if path.startswith("http") else (self.base_url.rstrip("/") + "/" + path.lstrip("/"))
        return path

    def get(self, path, params=None, headers=None, **kwargs):
        """GET 请求"""
        url = self._url(path)
        h = {**self.headers, **(headers or {})}
        return requests.get(url, params=params, headers=h, timeout=self.timeout, **kwargs)

    def post(self, path, json=None, data=None, headers=None, **kwargs):
        """POST 请求"""
        url = self._url(path)
        h = {**self.headers, **(headers or {})}
        return requests.post(url, json=json, data=data, headers=h, timeout=self.timeout, **kwargs)

    def put(self, path, json=None, data=None, headers=None, **kwargs):
        """PUT 请求"""
        url = self._url(path)
        h = {**self.headers, **(headers or {})}
        return requests.put(url, json=json, data=data, headers=h, timeout=self.timeout, **kwargs)

    def delete(self, path, headers=None, **kwargs):
        """DELETE 请求"""
        url = self._url(path)
        h = {**self.headers, **(headers or {})}
        return requests.delete(url, headers=h, timeout=self.timeout, **kwargs)


# 默认单例，用例中可直接 from utils.http_client import client
client = HttpClient()
