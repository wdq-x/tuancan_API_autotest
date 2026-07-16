---
name: api-doc-to-autotest
description: 根据研发提供的接口文档（Markdown 等）生成 Python 接口自动化测试脚本（Pytest + Allure + Requests）。在需要为新增或现有接口编写/补充自动化用例、或根据接口文档批量生成测试脚本时使用。
---

# 根据接口文档生成接口自动化测试

## 适用场景

- 研发提供了接口文档（如《xx 模块接口文档》.md），需要生成可执行的接口自动化用例
- 项目使用 **jiekou** 框架：Python + Pytest + Allure + `utils.http_client`
- 脚本需放在项目根目录下的 `test_case/` 中，与现有用例风格一致，并在每行或每段代码中添加可以理解的中文注释

## 工作流程

1. **阅读接口文档**：提取 Base URL、认证方式、统一响应约定（如 `code === 0` 表示成功）、各接口的 URL、方法、Query/Body 参数、响应 data 结构。
2. **确认项目约定**：查看 `config/project_information.py` 的 `base_url`、`default_headers`、`MANAGEMENT_TEST_ACCOUNT`、`ENABLE_WRITE_TESTS`；查看 `utils/http_client.py` 的 `client` 用法；参考已有用例 `test_case/test_02_api_order.py` 或 `test_01_api_bag.py` 的写法。
3. **生成测试脚本**：按下方「脚本结构规范」生成 `test_xx_api_模块名.py`，覆盖文档中前 N 个接口或用户指定的接口。
4. **收尾**：脚本放在 `test_case/`，如需登录则实现 Token 获取并写入 `client.headers`；在 README 中补充该用例的说明（接口列表、配置注意点）。

## 脚本结构规范

### 1. 文件头与常量

- 文件顶部 UTF-8 编码声明、模块 docstring（说明本文件测哪几个接口、登录方式、文档约定）。
- 登录 URL、登录 Body（若需登录）。
- 各被测接口的 **路径常量**（与 `base_url` 拼接，路径结尾**无**多余斜杠，与文档一致），例如：
  - `ORDER_STATUS_URL = "/api/canteen-management/order-status"`
  - `ORDER_DISTRIBUTOR_CATE_URL = "/api/canteen-management/order/distributor-cate"`

### 2. 登录与 Token（文档要求「需登录」时）

- 管理平台用例的账号必须直接从 `config.project_information.MANAGEMENT_TEST_ACCOUNT` 读取；所有模块共用这一套账号密码，不得新增按功能拆分的账号配置，也不得在脚本内写死账号密码或依赖运行时环境变量。
- 实现 `get_token()`：`client.post(LOGIN_URL, json=LOGIN_BODY)`，其中 `LOGIN_BODY` 基于上述统一账号配置构造；断言实际项目约定的 HTTP 状态和业务码，并从响应中解析 `token`（兼容 `data.token` / `data.access` / `data.access_token` 等），失败时抛出 `AssertionError` 并附带响应信息。
- 类级别 fixture（如 `订单带token`）：调用 `get_token()`，将 `client.headers["Authorization"] = f"Bearer {token}"`，`yield` 后在 teardown 中 `client.headers.pop("Authorization", None)`，保证本类用例均带 Token。

### 3. 断言辅助

- 封装 `_assert_200_or_404_msg(resp, msg_prefix)`：若 `status_code != 200`，抛出包含请求 URL、是否带 Authorization、响应片段等信息的 `AssertionError`，便于排查 404/鉴权问题。

### 4. 测试类与用例组织

- 使用 `@allure.parent_suite("接口自动化")`、`@allure.suite("模块名")`。
- 一个测试类对应一个业务模块（如「订单状态与配送商品类」），类内 `@pytest.fixture(scope="class", autouse=True)` 注入 Token（若需要）。
- 每个接口至少一条「默认/无参」用例；若文档中有 Query 参数（如 `name`、`sign`、`ordering`、`active`），为重要参数各写一条用例（等价类或典型值）。
- 用例内用 `with allure.step("步骤描述"):` 分段；步骤顺序：发请求 → 校验状态码 → 校验响应体（code、message、data）→ 校验 data 结构（类型、必含字段）。

### 5. 响应校验约定

- **HTTP**：期望 200 时用 `_assert_200_or_404_msg`；若文档说明某接口仅部分角色可访问（如 403），可在 403 时 `pytest.skip("...")`。
- **业务码**：文档约定 `code === 0` 表示成功时，`assert data.get("code") == 0`，失败信息带上 `message`。
- **data 结构**：根据文档「响应 data」表格，对列表项做字段断言，例如：
  - `assert isinstance(data["data"], list)`
  - `for item in data["data"]: assert "id" in item; assert "name" in item; ...`

### 6. 命名与风格

- 测试类名、方法名可中文（如 `Test订单状态与配送商品类`、`test_订单状态列表_默认`）。
- `@allure.feature("接口名或场景")` 与用例含义一致。
- 若需调试「登录 + 某接口是否带 Token」，可加一条 `test_00_登录获取token`，仅校验 `client.headers` 含 `Bearer ` 且请求该接口返回 200。

## 与项目的一致性

- 请求一律通过 `from utils.http_client import client` 的 `client.get/post/put/delete(path, params=..., json=...)`，**path 为相对 base_url 的路径**（无前导斜杠或带 `/` 均可，`http_client` 会拼接）。
- 不在脚本内写死 `base_url`，由 `config.project_information` 统一配置。
- 管理平台写操作用例须读取 `config.project_information.ENABLE_WRITE_TESTS`；开启时使用带唯一标识的临时数据，并在 `finally` 中回收。
- 新增脚本命名：`test_<序号>_api_<模块>.py`，与现有 `test_01_api_bag.py`、`test_02_api_order.py` 一致。

## 输出与自检

- 生成的脚本应可直接在项目根目录执行，例如：
  - `pytest test_case/test_xx_api_模块.py -s -q --alluredir=./report/allure_result`
- 自检清单：
  - [ ] 文档中的 Base URL、认证方式、code 含义已体现在脚本注释或常量中
  - [ ] 每个被测接口至少有 1 条用例，且覆盖文档中的主要参数/场景
  - [ ] 需要登录的接口由 fixture 统一注入 Token，且 404 时断言信息便于排查
  - [ ] data 列表及子项字段断言与接口文档「响应 data」一致

## 参考文件

- 接口文档示例：`test_case/采购订单模块接口文档.md`（含 Base URL、认证、统一响应、各接口 URL/参数/响应说明）
- 脚本示例：`test_case/test_02_api_order.py`（登录、Token fixture、订单状态列表与配送商品类两个接口的完整用例与断言写法）
