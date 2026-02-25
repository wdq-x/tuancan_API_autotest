# 接口自动化测试框架（jiekou）

## 项目简介

本项目是一个**接口自动化测试框架**，参考团餐 UI 自动化项目（team_meal_autotest）的目录与运行方式，仅包含运行接口自动化所需的必要包、目录和用例模板。使用 **Python + Pytest + Requests + Allure** 实现。

## 项目结构

```
jiekou/
├── config/                    # 配置
│   ├── __init__.py
│   └── project_information.py # 环境 base_url、请求头、Allure 报告环境变量
├── utils/                     # 公共工具
│   ├── __init__.py
│   ├── tools.py               # 报告路径等
│   ├── report_optimize.py     # Allure 报告优化（环境信息、报告标题）
│   └── http_client.py        # HTTP 请求封装（get/post/put/delete）
├── test_case/                 # 接口测试用例
│   ├── test_api_demo.py       # 接口测试用例模板
│   ├── test_01_api_bag.py     # 配送包管理接口测试（列表、详情）
│   └── test_02_api_order.py  # 采购订单模块接口测试（订单状态列表、配送商与品类）
├── report/                    # 报告输出目录（运行后生成）
│   ├── allure_result/         # Allure 原始结果
│   └── allure_html/           # Allure HTML 报告
├── run.py                     # 运行入口
├── requirements.txt           # 依赖包
└── readme.md                  # 本说明
```

## 环境要求

- Python 3.x（推荐 3.8+）
- Pytest
- Allure 命令行工具（用于生成和查看报告）
- requests

## 依赖安装

```bash
pip install -r requirements.txt
```

## 配置说明

- **config/project_information.py**
  - `base_url`：接口基础地址，默认为 `https://httpbin.org`，请改为实际被测系统地址。
  - `default_headers`：默认请求头（如 Content-Type、Authorization 等）。
  - `timeout`：请求超时时间（秒）。
  - `ENV_VARS`：Allure 报告中的环境信息（项目名、测试人等）。

## 使用方法

### 1. 运行全部接口测试并生成报告

```bash
cd E:\jiekou
python run.py
```

将执行 `test_case` 下所有用例，生成 Allure 结果并打开 HTML 报告。

### 2. 命令行运行指定用例

```bash
cd E:\jiekou
pytest test_case/test_api_demo.py -s -q --alluredir=./report/allure_result
```

### 3. 查看已有报告

```bash
allure generate ./report/allure_result -o ./report/allure_html --clean
allure open ./report/allure_html
```

## 接口测试用例模板说明

**test_case/test_api_demo.py** 为用例模板，包含：

- 使用 `@allure.parent_suite`、`@allure.suite`、`@allure.feature` 组织用例与报告。
- 使用 `with allure.step("步骤描述"):` 记录步骤。
- 通过 `utils.http_client` 的 `client` 发送 GET/POST 等请求。
- 对 `resp.status_code`、`resp.json()` 做断言。

编写新用例时可直接复制该文件或类，修改 URL、参数和断言即可。

**test_case/test_01_api_bag.py** 为配送包管理前两个接口的自动化测试：
- **接口1 - 获取配送包列表** `GET /api/food-safety-monitoring/bag/`：默认分页、指定 page/size、ordering、search 等场景。
- **接口2 - 获取配送包详情** `GET /api/food-safety-monitoring/bag/{id}/`：先调列表取 id 再查详情，以及不存在的 id 校验。
使用前请在 **config/project_information.py** 中将 `base_url` 改为配送包接口所在环境地址，并在 `default_headers` 中配置 `Authorization: Bearer <JWT Token>`，或在 **test_01_api_bag.py** 中设置 `BAG_API_HEADERS`。

**test_case/test_02_api_order.py** 为采购订单模块前两个接口的自动化测试（对应《采购订单模块接口文档》）：
- **接口1 - 订单状态列表** `GET /api/canteen-management/order-status/`：无参数、按 name/sign/active/ordering 过滤等场景。
- **接口2 - 配送商与品类（下单用）** `GET /api/canteen-management/order/distributor-cate/`：无参数，根据 token 解析食堂返回配送商及品类；非学校用户会跳过。
文档约定 `code === 0` 表示成功。使用前请配置 `base_url` 与 JWT，或在脚本中设置 `ORDER_API_HEADERS`。

## 注意事项

1. 首次使用前请在 **config/project_information.py** 中修改 `base_url` 为实际接口地址。
2. 需要登录态时，可在 `default_headers` 中配置 Token，或在用例里调用登录接口后设置 `client.headers`。
3. 生成 Allure 报告前需已安装 Allure 命令行工具，并配置好环境变量。
4. **配送包用例**：若 `base_url` 仍为 `https://httpbin.org`，请求会发往 httpbin，配送包路径不存在会返回 **404**，导致列表/详情相关用例失败（仅「不存在的 id 返回 404」会通过）。请将 `base_url` 改为真实配送包服务地址后再跑全绿。
5. **Allure 报告**：本项目使用 `allure-pytest>=2.10.0` 以兼容 pytest 7+。若执行 `allure generate` 时出现 `Unrecognized field "titlePath"`，说明本机 **Allure 命令行版本较旧**，请将 Allure CLI 升级至 **2.24+**（[下载](https://github.com/allure-framework/allure2/releases)），不要降级 allure-pytest 到 2.8.6，否则会报 `'str' object has no attribute 'iter_parents'`。

## 维护说明

- 新增接口用例请放在 `test_case/` 下，建议以 `test_` 开头、`_api` 或功能模块命名。
- 公共请求封装、鉴权等可放在 `utils/`，如扩展 `http_client.py` 或新增模块。
- 多环境可在 `config/project_information.py` 中增加多组 base_url，按环境切换。
