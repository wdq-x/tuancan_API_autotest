# 移动端点位勘察接口自动化

测试文件：

```text
test_01_api_mobile_site_survey.py
```

接口契约来自移动端 Flutter 项目 `E:\canteen_operate_platfrom_app`：

- `lib/app/modules/site_survey/controllers/site_survey_request.dart`
- `lib/app/modules/site_survey/controllers/site_survey_controller.dart`
- `lib/app/modules/site_survey/models/site_survey_models.dart`

## 覆盖范围

- 移动端登录：`POST /v1/login`，请求体携带 `client_type=mobile`。
- 勘察列表：未登录、分页、关键字和状态搜索。
- 勘察单：创建、`request_id` 幂等、详情、版本更新、删除和删除后不存在。
- 层级采集：学校、设备、点位、照片、圆形/矩形标注、校验和设备删除后的点位/照片级联删除。
- 草稿整体提交：学校/设备/照片一次性提交、版本冲突和草稿内重名学校。
- 导出校验：未完成勘察的 blocker、导出阻断和单校预览未选学校。
- 异常：未登录、非法分页、创建缺少项目/客户名称、不存在勘察单、非法设备数量、非法照片标记、学校重名、资源不存在、版本冲突和导出阻断。

点位勘察单通过删除接口软删除，测试数据均带 `AT-移动端点位勘察-` 前缀。照片水印和绘制是 Flutter 设备交互；接口用例覆盖水印上传后提交的附件元数据、标记类型和标记坐标契约。

## 账号与执行

移动端和管理平台统一使用 `MANAGEMENT_TEST_USERNAME`、`MANAGEMENT_TEST_PASSWORD`。CI 从 GitHub Secrets 注入，本地 `python run.py` 从被 Git 忽略的 `config/local_test_accounts.py` 读取。

```powershell
cd E:\jiekou
python -m pytest test_case/移动端/点位勘察/test_01_api_mobile_site_survey.py -s -q --alluredir=./report/allure_result
```
