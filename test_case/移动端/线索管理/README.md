# 移动端线索管理接口自动化

脚本对应 Flutter 项目 `E:\canteen_operate_platfrom_app` 的线索管理模块，测试文件为：

```text
test_01_api_mobile_lead_management.py
```

接口契约来自以下移动端代码：

- `lib/app/modules/login/controllers/login_request.dart`
- `lib/app/modules/clue_management/controllers/clue_request.dart`
- `lib/app/modules/clue_management/controllers/channel_option_request.dart`
- `lib/app/modules/customer_management/controllers/customer_request.dart`

## 覆盖范围

- 移动端登录：`POST /v1/login`，请求体固定携带 `client_type=mobile`。
- 线索列表：分页/加载更多、名称搜索、业态、来源渠道、四种状态 Tab 与今天/近 7 天/近 30 天/自定义时间筛选。
- 来源渠道选项：`GET /v1/channels/options?status=active&limit=500`。
- 线索详情、创建、编辑、按状态变更、删除及参数校验。
- 详情展示数据：附件元数据、跟进记录和操作记录。
- 线索转客户：按移动端客户表单字段调用 `POST /v1/leads/{id}/convert-to-customer`，并验证渠道继承和联动清理。

写操作只创建 `AT-移动端线索-` 前缀的临时线索，测试结束时会删除。它会复用渠道选项中的合作中渠道，不会创建、编辑或删除环境已有渠道。

## 账号配置

移动端与管理平台统一使用：

```text
MANAGEMENT_TEST_USERNAME
MANAGEMENT_TEST_PASSWORD
```

CI 从 GitHub Secrets 注入这两个变量；本地 `python run.py` 从被 Git 忽略的
`config/local_test_accounts.py` 读取账号。移动端不维护单独的 CI 凭据。

测试账号必须具备移动端登录、线索管理、客户转换和线索删除权限。若没有可用的合作中渠道或写操作关闭，相关写用例会跳过。

## 执行

```powershell
cd E:\jiekou
python -m pytest test_case/移动端/线索管理/test_01_api_mobile_lead_management.py -s -q --alluredir=./report/allure_result
```
