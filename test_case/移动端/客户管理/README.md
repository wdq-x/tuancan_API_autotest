# 移动端客户管理接口自动化

测试文件：

```text
test_01_api_mobile_customer_management.py
```

接口契约来自移动端 Flutter 项目 `E:\canteen_operate_platfrom_app` 的以下文件：

- `lib/app/modules/customer_management/controllers/customer_request.dart`
- `lib/app/modules/customer_management/controllers/customer_management_controller.dart`
- `lib/app/modules/customer_management/controllers/add_customer_controller.dart`
- `lib/app/modules/customer_management/controllers/customer_renew_controller.dart`
- `lib/app/data/models/customer_model.dart`

## 覆盖范围

- 移动端登录：`POST /v1/login`，请求体携带 `client_type=mobile`。
- 客户列表：首次加载、滚动加载下一页、部署模式和状态筛选。
- 客户查询与提交参数校验。
- 新增客户：按移动端表单先选择来源线索，再调用 `POST /v1/customers`；验证名称、部署方式、渠道、线索、域名、状态、注册时间和服务有效期筛选。
- 新增删除闭环：创建、列表回查、详情回查、删除和删除后详情不存在；同名客户创建、删除不存在客户等异常校验。
- 客户详情：验证客户核心字段、来源线索/渠道关系和附件元数据。
- 客户详情操作：续费、禁用、启用及删除。
- 线索转客户：`POST /v1/leads/{lead_id}/convert-to-customer` 和删除线索时的客户联动清理。

写操作仅创建 `AT-移动端客户-` 和 `AT-移动端客户线索-` 前缀的临时数据，并在用例结束时清理。来源渠道使用环境中已有的合作中渠道，不会修改已有渠道。

## 账号与执行

移动端与管理平台统一使用 `MANAGEMENT_TEST_USERNAME`、`MANAGEMENT_TEST_PASSWORD`：CI 从 GitHub Secrets 注入，本地 `python run.py` 从被 Git 忽略的 `config/local_test_accounts.py` 读取。

```powershell
cd E:\jiekou
python -m pytest test_case/移动端/客户管理/test_01_api_mobile_customer_management.py -s -q --alluredir=./report/allure_result
```
