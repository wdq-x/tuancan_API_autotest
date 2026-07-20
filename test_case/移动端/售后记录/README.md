# 移动端售后记录接口自动化

测试文件：

```text
test_01_api_mobile_after_sales_records.py
```

接口契约来自移动端 Flutter 项目 `E:\canteen_operate_platfrom_app`：

- `lib/app/modules/after_sales_records/controllers/after_sales_record_request.dart`
- `lib/app/modules/after_sales_records/controllers/after_sales_record_controller.dart`
- `lib/app/modules/after_sales_records/controllers/after_sales_record_detail_controller.dart`
- `lib/app/modules/after_sales_records/models/after_sales_record_models.dart`

## 覆盖范围

- 移动端登录：`POST /v1/login`，请求体携带 `client_type=mobile`。
- 项目选择：`GET /v1/after-sales-records/mobile/projects` 的分页、关键字搜索和项目成员选择。
- 我的记录：`GET /v1/after-sales-records/my` 的首页、加载下一页和新建记录回查。
- 售后记录提交：项目、处理人员、现场照片、客户签字、上门时间、处理结果、备注和 `source_client=mobile`。
- 详情：记录核心字段、照片和签字的预览地址。
- 幂等：同一移动端 `request_id` 重试返回同一条记录，不产生重复记录。
- 异常：未登录、非法分页、不存在记录/项目成员、缺少必填字段、非法处理结果、现场照片为空、不存在项目和不存在处理人员。
- 数据清理：售后记录模块没有删除 API。测试在独立的 `AT-移动端售后-` 临时项目下创建记录，随后关闭并删除该项目；`after_sales_records.project_id` 的外键级联删除会清理记录。

移动端拍照、水印和签字绘制属于 Flutter 设备交互；接口用例覆盖它们上传后提交到服务端的附件元数据契约。

## 账号与执行

移动端和管理平台统一使用 `MANAGEMENT_TEST_USERNAME`、`MANAGEMENT_TEST_PASSWORD`。CI 从 GitHub Secrets 注入，本地 `python run.py` 从被 Git 忽略的 `config/local_test_accounts.py` 读取。

```powershell
cd E:\jiekou
python -m pytest test_case/移动端/售后记录/test_01_api_mobile_after_sales_records.py -s -q --alluredir=./report/allure_result
```
