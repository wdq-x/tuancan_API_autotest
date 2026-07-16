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
│   └── http_client.py         # HTTP 请求封装（get/post/put/patch/delete）
├── test_case/                 # 接口测试用例（按业务模块分目录）
│   ├── __init__.py
│   ├── 食堂管理/
│   │   ├── 采购管理/          # 采购订单、验收单
│   │   │   ├── test_01_api_order.py              # 采购订单模块全量 14 个接口测试
│   │   │   └── test_02_api_acceptance_inspection.py  # 验收单创建接口测试
│   │   └── 菜品管理/          # 档口与商品
│   │       ├── README.md      # 档口与商品接口说明
│   │       └── test_01_api_stall_product.py      # 档口/就餐时段/商品属性/分类/商品库等接口测试
│   └── 销售管理/              # 销售备货、销售订单
│       └── 销售管理/
│           ├── test_01_api_distributor_order_line.py
│           └── test_02_api_orders.py
│   └── 食安监管/              # 配送包管理
│       └── 采购管理/
│           └── test_01_api_bag.py                # 配送包管理 7 个接口测试
├── report/                    # 报告输出目录（运行后生成）
│   ├── allure_result/         # Allure 原始结果
│   └── allure_html/           # Allure HTML 报告
├── run.py                     # 运行入口（可修改 case_list 指定要执行的用例）
├── requirements.txt          # 依赖包
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

### 1. 运行接口测试并生成报告

```bash
cd E:\jiekou
python run.py
```

默认执行 `run.py` 中 `case_list` 指定的用例（可为单个文件或目录），生成 Allure 结果并打开 HTML 报告。若要执行整个 `test_case` 目录，将 `case_list` 改为 `test_case` 或对应子目录（如 `test_case/食堂管理/采购管理`）。

### 2. 命令行运行指定用例

```bash
cd E:\jiekou
# 运行食堂管理-采购管理
pytest test_case/食堂管理/采购管理/test_01_api_order.py -s -q --alluredir=./report/allure_result
# 运行食堂管理-菜品管理（档口与商品）
pytest test_case/食堂管理/菜品管理/test_01_api_stall_product.py -s -q --alluredir=./report/allure_result
# 运行销售管理-销售备货
pytest test_case/销售管理/test_01_api_distributor_order_line.py -s -q --alluredir=./report/allure_result
# 运行销售管理-销售订单
pytest test_case/销售管理/test_02_api_orders.py -s -q --alluredir=./report/allure_result
# 运行食安监管-配送包管理
pytest test_case/食安监管/采购管理/test_01_api_bag.py -s -q --alluredir=./report/allure_result
```

### 3. 查看已有报告

```bash
allure generate ./report/allure_result -o ./report/allure_html --clean
allure open ./report/allure_html
```

## 接口测试用例说明

用例按业务模块放在 **test_case/** 下（如 **test_case/食堂管理/**、**test_case/销售管理/**），编写新用例可参考现有脚本（登录与 Token、URL 常量、Allure 分层、响应断言等）。

**通用约定**：
- 使用 `@allure.parent_suite`、`@allure.suite`、`@allure.feature` 组织用例与报告。
- 使用 `with allure.step("步骤描述"):` 记录步骤。
- 通过 `utils.http_client` 的 `client` 发送 GET/POST 等请求，对 `resp.status_code`、`resp.json()` 做断言。

---

**test_case/食堂管理/采购管理/test_01_api_order.py** — 采购订单模块**全量 14 个接口**（对应《采购订单模块接口文档》）：
- **接口1 - 订单状态列表** `GET /api/canteen-management/order-status/`：无参数、按 name/sign/active/ordering 过滤等场景。
- **接口2 - 配送商与品类（下单用）** `GET /api/canteen-management/order/distributor-cate/`：无参数，根据 token 解析食堂返回配送商及品类；非学校用户会跳过。
- **接口3 - 用户信息（下单用）**、**接口4 - 食堂仓库列表**、**接口5 - 增加订单商品-可选商品列表**、**接口6 - 配送商商品列表（选品用）**、**接口7 - 采购计划提交**。
- **接口8 - 订单列表**、**接口9 - 订单各状态数量（Tab）**、**接口10 - 订单详情**、**接口11 - 订单配送商下拉**。
- **接口12 - 批量提交订单**、**接口13 - 订单取消**、**接口14 - 订单编辑/保存**。
- 文档约定 `code === 0` 表示成功。使用前请配置 `base_url` 与 JWT，或在脚本中设置 `ORDER_API_HEADERS`。

**test_case/食堂管理/采购管理/test_02_api_acceptance_inspection.py** — **食堂管理-验收单创建**（依据《验收单创建接口开发文档》）：
- **被测接口**：`POST /api/canteen-management/acceptance-inspection/` 创建验收单。
- **请求体**：`order_id`（必填）、`line_ids`（必填，非空，订单明细 id 列表）。
- **覆盖场景**：登录与 Token、正常创建（待收货订单+明细）、缺少 order_id/line_ids、line_ids 为空、订单不存在、无效 line_ids、line_ids 重复等。
- 与订单模块共用同一登录接口与 `base_url`；成功用例依赖环境中存在「待收货」状态订单及明细，否则对应用例会 skip。

**test_case/食堂管理/菜品管理/test_01_api_stall_product.py** — **食堂管理-档口与商品**（依据《API_接口说明_档口与商品.md》）：
- **档口管理**：档口列表（分页）、档口选项数据、详情/创建/更新/删除、批量删除、启用停用、批量更新状态。
- **就餐时段**：就餐时段列表。
- **商品属性 / 属性值**：列表、详情、批量删除等。
- **商品分类**：列表、详情、批量删除。
- **商品库**：商品列表（分页）、单位列表、详情等。
- 详情类用例从对应列表取第一条记录的 `id` 请求；列表为空则跳过。响应约定 `code === 200` 或 `code === 0` 表示成功。更多说明见 **test_case/食堂管理/菜品管理/README.md**。

**test_case/销售管理/test_01_api_distributor_order_line.py** — **销售备货模块**（依据《销售备货前端开发接口说明》）：
- **接口1 - 获取销售备货列表** `GET /api/sale-management/distributor-order-line/list`：分页、品类/商品名/到货时间筛选。
- **接口2 - 获取商品品类列表（下拉）** `GET /api/sale-management/distributor-order-line/categories`：无参数，返回当前配送商有效合同期内品类。
- **接口3 - 获取销售备货详情** `POST /api/sale-management/distributor-order-line/detail`：必填 `order_line_ids`、`product_id`，可选商品名/规格/单位。
- **接口4 - 导出销售备货单（Excel）** `GET /api/sale-management/distributor-order-line/export`：与列表相同筛选参数，成功返回 Excel 流，无数据返回 JSON code 400。
- **权限**：仅**配送商**身份可访问；非配送商返回 403，相关用例会 skip。使用前请在脚本中配置配送商账号（`LOGIN_BODY` 的 `username/password`、`department_type="distributor"`、`department_id`），并确保 `base_url` 正确。

**test_case/销售管理/test_02_api_orders.py** — **销售订单模块**（依据《销售订单接口文档说明》）：
- **接口1 - 订单列表** `GET /api/sale-management/orders`：分页、订单号/学校/到货时间/状态筛选、排序。
- **接口2 - 订单状态统计** `GET /api/sale-management/orders/statistics`：无参数，返回各状态数量及 total。
- **接口3 - 导出订单商品 Excel** `GET /api/sale-management/orders/export?order_id=`：必填 order_id，成功返回 Excel 流。
- **接口4 - 订单详情** `GET /api/sale-management/orders/{id}`：含 line_ids、licence_ids 等。
- **接口5 - 判断是否触发警告** `POST /api/sale-management/orders/{id}/check-warnings`：Body 含 line_id、delivering_quantity。
- **接口6 - 标记已读**、**接口7 - 受理订单**、**接口8 - 确认订单修改**、**接口9 - 确认发货**、**接口10 - 刷新生产日期**。
- **接口11 - 打印配送单 PDF** `GET /api/sale-management/orders/{id}/print-report`。
- **接口12/13/14 - 批次拆分**：初始化、保存、撤销 `POST .../orders/{id}/lines/{line_id}/batch-split[/save|/remove]`。
- **接口15 - 合同学校列表** `GET /api/sale-management/distributor/schools`。
- **接口16 - 人员与车辆列表** `GET /api/sale-management/distributor/personnel-and-vehicles`。
- **权限**：仅**配送商**可访问（IsDistributorOnly）；非配送商 403 时用例 skip。依赖订单数据的用例（详情、导出、标记已读、受理等）在列表无数据时 skip。使用前请配置配送商账号与 `base_url`。

**test_case/食安监管/采购管理/test_01_api_bag.py** — **食安监管-配送包管理**（依据《API接口文档-配送包管理.md》）：
- **接口1 - 获取配送包列表** `GET /api/food-safety-monitoring/bag/`：分页、department、is_edit、search、ordering。
- **接口2 - 获取配送包详情** `GET /api/food-safety-monitoring/bag/{id}/`：含 category_line 等。
- **接口3 - 创建配送包** `POST /api/food-safety-monitoring/bag/`：name、category_line（必填），同部门包名唯一。
- **接口4 - 更新配送包** `PATCH /api/food-safety-monitoring/bag/{id}/`：仅 is_edit=true 可更新。
- **接口5 - 删除配送包** `DELETE /api/food-safety-monitoring/bag/{id}/`：未被合同引用才可删除。
- **接口6 - 获取可选品类列表** `GET /api/food-safety-monitoring/bag/available-categories/`：department、exclude_bag_id。
- **接口7 - 查询关联的合同明细** `GET /api/food-safety-monitoring/bag/{id}/contract-lines/`。
- **响应约定**：本模块 `code === 200` 表示成功（与部分其他模块的 code=0 不同）。需登录，与食堂/销售模块共用 `POST /api/users/auth/login`；使用前请配置 `base_url` 与可登录账号（脚本内 `LOGIN_BODY`）。

## 注意事项

1. 首次使用前请在 **config/project_information.py** 中修改 `base_url` 为实际接口地址。
2. 需要登录态时，可在 `default_headers` 中配置 Token，或在用例里调用登录接口后设置 `client.headers`。
3. 生成 Allure 报告前需已安装 Allure 命令行工具，并配置好环境变量。
4. **代理**：接口请求默认**不走系统代理**（不读 `HTTP_PROXY`/`HTTPS_PROXY`），直连 `base_url`。若本机开了代理但代理未运行，会导致 `ProxyError`；框架已在 `utils/http_client.py` 中显式禁用代理，避免该问题。如需走代理，可在调用时传入 `proxies` 或自行改回使用环境变量。
5. **Allure 报告**：本项目使用 `allure-pytest>=2.10.0` 以兼容 pytest 7+。若执行 `allure generate` 时出现 `Unrecognized field "titlePath"`，说明本机 **Allure 命令行版本较旧**，请将 Allure CLI 升级至 **2.24+**（[下载](https://github.com/allure-framework/allure2/releases)），不要降级 allure-pytest 到 2.8.6，否则会报 `'str' object has no attribute 'iter_parents'`。

## 维护说明

- 新增接口用例请放在 **test_case/** 下，按业务模块分子目录（如 `test_case/食堂管理/采购管理`、`test_case/食堂管理/菜品管理`、`test_case/销售管理`），建议文件名以 `test_` 开头、`_api` 或功能命名。
- 公共请求封装、鉴权等可放在 `utils/`，如扩展 `http_client.py` 或新增模块。
- 多环境可在 `config/project_information.py` 中增加多组 base_url，按环境切换。
- 通过修改 **run.py** 中的 `case_list` 可指定每次运行的用例文件或目录。

## 根据接口文档生成用例（Cursor Skill）

本项目提供 Cursor 技能 **api-doc-to-autotest**，用于根据研发提供的接口文档（如 Markdown）自动生成与现有风格一致的接口自动化测试脚本。

- **位置**：`.cursor/skills/接口文档生成接口自动化测试/SKILL.md`
- **何时使用**：需要为新增或现有接口编写/补充自动化用例、或根据《xx 模块接口文档》批量生成测试脚本时，在 Cursor 中引用该 skill 或说明「根据接口文档生成接口自动化测试」即可。
- **参考**：生成规则与 `test_case/食堂管理/采购管理/test_01_api_order.py` 一致（登录与 Token、URL 常量、Allure 分层、响应断言约定等）；接口文档示例可参考项目内或 tuancan-docs 中的《采购订单模块接口文档》《API_接口说明_档口与商品》等。

## 管理平台渠道管理

管理平台的测试地址、默认请求头、渠道管理测试账号和写操作开关统一维护在 `config/project_information.py`：

- `base_url`：当前为本地管理平台 `http://localhost:3001`。
- `MANAGEMENT_TEST_ACCOUNT`：唯一的管理平台测试账号。渠道、线索、客户和后续管理平台用例均使用此账号登录，因此它需要具备相应模块权限。
- `ENABLE_WRITE_TESTS`：开启后执行渠道、线索、客户的完整写入与清理链路。

渠道管理测试脚本会直接读取以上配置，不需要再设置环境变量：

```bash
python -m pytest test_case/管理平台/销售管理/test_01_api_channel_management.py -s -q
# 运行线索管理
python -m pytest test_case/管理平台/销售管理/test_02_api_lead_management.py -s -q
# 运行客户管理
python -m pytest test_case/管理平台/销售管理/test_03_api_customer_management.py -s -q
# 运行销售商品管理
python -m pytest test_case/管理平台/销售管理/test_04_api_sales_product_management.py -s -q
# 运行销售报价单管理
python -m pytest test_case/管理平台/销售管理/test_05_api_sales_quotation_management.py -s -q
```
