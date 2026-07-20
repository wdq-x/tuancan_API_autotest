# 移动端项目交付接口自动化

测试文件：

```text
test_01_api_mobile_project_delivery.py
```

接口契约来自移动端 Flutter 项目 `E:\canteen_operate_platfrom_app` 的以下文件：

- `lib/app/modules/project_delivery/controllers/project_delivery_request.dart`
- `lib/app/modules/project_delivery/controllers/delivery_todo_controller.dart`
- `lib/app/modules/project_delivery/controllers/node_submit_controller.dart`
- `lib/app/modules/project_delivery/controllers/node_confirm_controller.dart`
- `lib/app/modules/project_delivery/controllers/rectification_submit_controller.dart`
- `lib/app/modules/project_delivery/controllers/demand_create_controller.dart`
- `lib/app/modules/project_delivery/models/project_delivery_models.dart`

## 覆盖范围

- 移动端登录：`POST /v1/login`，请求体固定携带 `client_type=mobile`。
- 项目交付待办：鉴权、分页、非法页码，以及全部、节点处理、验收确认、资料补充、整改复核、需求确认六类查询。
- 项目生命周期：创建参数校验、创建后回查项目/节点/待办、关闭、删除和删除后项目不存在。
- 节点任务：项目、节点、节点详情和节点待办关联关系。
- 节点资料：创建资料槽位、资料版本必填字段校验、调用 `/v1/upload` 上传真实临时文件、按上传结果创建资料版本、查看历史、删除版本并清理上传对象。
- 整改提交：整改待办、整改说明必填校验、附件元数据和提交后待办关闭。
- 需求登记：标题/描述最小长度校验、选择来源节点、标题/描述/现场/影响范围提交、需求列表和需求确认待办。
- 节点确认：驳回、重新提交、验收确认通过和待办状态同步。
- 节点异常：未提交节点直接确认时返回状态冲突。

## 数据隔离

写操作会创建 `AT-移动端项目交付-` 前缀的临时项目。节点、资料、整改和需求均只属于这些临时项目；结束时先将项目置为 `closed`，再调用删除接口清理。

项目创建、跳过非验收节点和节点提交仅用于准备确认页可操作状态。移动端实际提交的资料版本、整改、需求、节点确认和节点驳回请求均按 Flutter 请求层的字段发送，并携带 `source_client=mobile`。

## 账号与执行

移动端和管理平台统一使用 `MANAGEMENT_TEST_USERNAME`、`MANAGEMENT_TEST_PASSWORD`。CI 从 GitHub Secrets 注入，本地 `python run.py` 从被 Git 忽略的 `config/local_test_accounts.py` 读取。

```powershell
cd E:\jiekou
python -m pytest test_case/移动端/项目交付/test_01_api_mobile_project_delivery.py -s -q --alluredir=./report/allure_result
```
