# 配送包管理接口文档

## 一、接口概述

**基础路径**: `/api/food-safety-monitoring/bag/`

**认证方式**: JWT Token（需要在请求头中携带 `Authorization: Bearer {token}`）

**数据格式**: JSON

---

## 二、接口列表

### 1. 获取配送包列表

**接口地址**: `GET /api/food-safety-monitoring/bag/`

**接口描述**: 分页查询配送包列表，支持过滤、搜索、排序

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| page | integer | 否 | 页码，默认1 | 1 |
| size | integer | 否 | 每页数量，默认20 | 20 |
| department | integer | 否 | 部门ID（过滤） | 1 |
| is_edit | boolean | 否 | 是否可编辑（过滤） | true |
| search | string | 否 | 搜索关键词（搜索name、name_category） | "标准包" |
| ordering | string | 否 | 排序字段，支持：id、sequence、name、create_date，默认id | "-create_date" |

**请求示例**:
```http
GET /api/food-safety-monitoring/bag/?page=1&size=20&department=1&is_edit=true&search=标准包&ordering=-create_date
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

**响应格式**:
```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "id": 1,
      "sequence": 1,
      "name": "标准包",
      "department": 1,
      "department_name": "XX学校",
      "is_edit": true,
      "name_category": "标准包(主食,蔬菜,肉类)",
      "category_count": 3,
      "create_date": "2024-01-01T10:00:00Z",
      "write_date": "2024-01-01T10:00:00Z"
    }
  ],
  "count": 10,
  "next": "http://localhost:8000/api/food-safety-monitoring/bag/?page=2",
  "previous": null
}
```

**响应字段说明**:

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 配送包ID |
| sequence | integer | 序号（自动计算，用于显示） |
| name | string | 包名称 |
| department | integer | 创建人部门ID |
| department_name | string | 创建人部门名称 |
| is_edit | boolean | 是否可编辑（false表示已被合同使用） |
| name_category | string | 显示名称（自动计算：name + (category1,category2,...)） |
| category_count | integer | 关联品类数量 |
| create_date | datetime | 创建时间 |
| write_date | datetime | 更新时间 |

---

### 2. 获取配送包详情

**接口地址**: `GET /api/food-safety-monitoring/bag/{id}/`

**接口描述**: 获取指定配送包的详细信息，包括关联的品类列表

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | integer | 是 | 配送包ID |

**请求示例**:
```http
GET /api/food-safety-monitoring/bag/1/
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

**响应格式**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": 1,
    "sequence": 1,
    "name": "标准包",
    "department": {
      "id": 1,
      "name": "XX学校",
      "code": "SCH001"
    },
    "is_edit": true,
    "name_category": "标准包(主食,蔬菜,肉类)",
    "category_line": [
      {
        "id": 1,
        "name": "主食",
        "code": "CAT001"
      },
      {
        "id": 2,
        "name": "蔬菜",
        "code": "CAT002"
      },
      {
        "id": 3,
        "name": "肉类",
        "code": "CAT003"
      }
    ],
    "create_date": "2024-01-01T10:00:00Z",
    "write_date": "2024-01-01T10:00:00Z",
    "create_uid": 1,
    "write_uid": 1
  }
}
```

**响应字段说明**:

| 字段名 | 类型 | 说明 |
|--------|------|------|
| category_line | array | 关联品类列表，每个元素包含：id、name、code |

---

### 3. 创建配送包

**接口地址**: `POST /api/food-safety-monitoring/bag/`

**接口描述**: 创建新的配送包

**请求体**:

```json
{
  "name": "标准包",
  "category_line": [1, 2, 3]
}
```

**请求字段说明**:

| 字段名 | 类型 | 必填 | 说明 | 约束 |
|--------|------|------|------|------|
| name | string | 是 | 包名称 | 最大长度10字符，同部门下必须唯一 |
| category_line | array[integer] | 是 | 品类ID列表 | 至少选择一个品类，不能选择已被同部门其他配送包使用的品类 |
| department | integer | 否 | 创建人部门ID | 不传则使用当前用户部门 |

**请求示例**:
```http
POST /api/food-safety-monitoring/bag/
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
Content-Type: application/json

{
  "name": "标准包",
  "category_line": [1, 2, 3]
}
```

**响应格式**:
```json
{
  "code": 200,
  "message": "创建成功",
  "data": {
    "id": 1,
    "sequence": 1,
    "name": "标准包",
    "department": {
      "id": 1,
      "name": "XX学校"
    },
    "is_edit": true,
    "name_category": "标准包(主食,蔬菜,肉类)",
    "category_line": [
      {
        "id": 1,
        "name": "主食"
      },
      {
        "id": 2,
        "name": "蔬菜"
      },
      {
        "id": 3,
        "name": "肉类"
      }
    ],
    "create_date": "2024-01-01T10:00:00Z",
    "write_date": "2024-01-01T10:00:00Z"
  }
}
```

**业务规则**:
1. `name_category` 字段会自动计算：`name + (category1,category2,...)`
2. `is_edit` 字段默认为 `true`
3. 同部门下包名称必须唯一
4. 不能选择已被同部门其他配送包使用的品类
5. 至少需要关联一个品类

**错误响应**:
```json
{
  "code": 400,
  "message": "该部门下包名称已存在",
  "data": null
}
```

---

### 4. 更新配送包

**接口地址**: `PATCH /api/food-safety-monitoring/bag/{id}/`

**接口描述**: 更新配送包信息

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | integer | 是 | 配送包ID |

**请求体**:

```json
{
  "name": "标准包（更新）",
  "category_line": [1, 2, 3, 4]
}
```

**请求字段说明**:

| 字段名 | 类型 | 必填 | 说明 | 约束 |
|--------|------|------|------|------|
| name | string | 否 | 包名称 | 最大长度10字符，同部门下必须唯一 |
| category_line | array[integer] | 否 | 品类ID列表 | 至少选择一个品类，不能选择已被同部门其他配送包使用的品类 |

**请求示例**:
```http
PATCH /api/food-safety-monitoring/bag/1/
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
Content-Type: application/json

{
  "name": "标准包（更新）",
  "category_line": [1, 2, 3, 4]
}
```

**响应格式**:
```json
{
  "code": 200,
  "message": "更新成功",
  "data": {
    "id": 1,
    "name": "标准包（更新）",
    "name_category": "标准包（更新）(主食,蔬菜,肉类,水果)",
    ...
  }
}
```

**业务规则**:
1. 如果 `is_edit=false`，不允许更新（返回错误：该配送包已被合同使用，不允许修改）
2. `department` 字段不允许修改
3. 更新后 `name_category` 会自动重新计算

**错误响应**:
```json
{
  "code": 400,
  "message": "该配送包已被合同使用，不允许修改",
  "data": null
}
```

---

### 5. 删除配送包

**接口地址**: `DELETE /api/food-safety-monitoring/bag/{id}/`

**接口描述**: 删除配送包（逻辑删除）

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | integer | 是 | 配送包ID |

**请求示例**:
```http
DELETE /api/food-safety-monitoring/bag/1/
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

**响应格式**:
```json
{
  "code": 200,
  "message": "删除成功",
  "data": null
}
```

**业务规则**:
1. 如果配送包被合同使用，不允许删除（返回错误：删除包中存在引用的合同，不可删除）
2. 删除是逻辑删除，`active` 字段设为 `false`

**错误响应**:
```json
{
  "code": 400,
  "message": "删除包中存在引用的合同，不可删除",
  "data": null
}
```

---

### 6. 获取可选品类列表

**接口地址**: `GET /api/food-safety-monitoring/bag/available-categories/`

**接口描述**: 获取当前部门下可选的品类列表（排除已被其他配送包使用的品类）

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| department | integer | 否 | 部门ID（不传则使用当前用户部门） | 1 |
| exclude_bag_id | integer | 否 | 排除的配送包ID（更新时使用） | 1 |

**请求示例**:
```http
GET /api/food-safety-monitoring/bag/available-categories/?department=1&exclude_bag_id=1
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

**响应格式**:
```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "id": 1,
      "name": "主食",
      "code": "CAT001"
    },
    {
      "id": 2,
      "name": "蔬菜",
      "code": "CAT002"
    }
  ],
  "count": 2
}
```

**业务规则**:
1. 返回当前部门下未被其他配送包使用的品类
2. 如果提供了 `exclude_bag_id`，则排除该配送包已使用的品类（用于更新场景）

---

### 7. 查询关联的合同明细

**接口地址**: `GET /api/food-safety-monitoring/bag/{id}/contract-lines/`

**接口描述**: 查询使用该配送包的合同明细列表

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | integer | 是 | 配送包ID |

**请求示例**:
```http
GET /api/food-safety-monitoring/bag/1/contract-lines/
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

**响应格式**:
```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "id": 1,
      "contract_id": 1,
      "contract_coding": "HT202401001",
      "distributor_id": 1,
      "distributor_name": "XX配送商"
    }
  ],
  "count": 1
}
```

---

## 三、错误码说明

| 错误码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 参数错误或业务规则违反 |
| 401 | 未认证（需要登录） |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器错误 |

---

## 四、业务规则总结

### 1. 自动计算字段
- **name_category**: 自动计算为 `name + (category1,category2,...)`
- **sequence**: 列表查询时自动计算，用于显示序号

### 2. 唯一性约束
- 同部门下包名称必须唯一

### 3. 品类域限制
- 同一部门下，一个品类只能被一个配送包使用
- 创建或更新时，不能选择已被其他配送包使用的品类

### 4. 编辑限制
- `is_edit=false` 时，不允许更新（已被合同使用）
- `is_edit` 字段会在合同创建/更新时自动更新

### 5. 删除限制
- 被合同使用的配送包不允许删除

---

## 五、前端开发建议

### 1. 列表页面
- 使用分页组件显示数据
- 提供搜索框（搜索 name 和 name_category）
- 提供过滤选项（department、is_edit）
- 显示 `is_edit` 状态，禁用状态显示为灰色

### 2. 创建/编辑页面
- 使用下拉多选组件选择品类
- 调用 `available-categories` 接口获取可选品类
- 实时验证包名称唯一性
- 显示 `name_category` 预览

### 3. 删除操作
- 删除前检查是否被合同使用
- 显示友好的错误提示

### 4. 状态显示
- `is_edit=true`: 显示为"可编辑"，可进行编辑操作
- `is_edit=false`: 显示为"已使用"，禁用编辑按钮

---

## 六、示例代码

### JavaScript (Axios)
```javascript
import axios from 'axios';

const API_BASE = '/api/food-safety-monitoring/bag/';
const token = 'your-jwt-token';

// 获取列表
async function getBagList(params) {
  const response = await axios.get(API_BASE, {
    params: params,
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  return response.data;
}

// 创建配送包
async function createBag(data) {
  const response = await axios.post(API_BASE, data, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    }
  });
  return response.data;
}

// 更新配送包
async function updateBag(id, data) {
  const response = await axios.patch(`${API_BASE}${id}/`, data, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    }
  });
  return response.data;
}

// 删除配送包
async function deleteBag(id) {
  const response = await axios.delete(`${API_BASE}${id}/`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  return response.data;
}

// 获取可选品类
async function getAvailableCategories(departmentId, excludeBagId) {
  const params = {};
  if (departmentId) params.department = departmentId;
  if (excludeBagId) params.exclude_bag_id = excludeBagId;
  
  const response = await axios.get(`${API_BASE}available-categories/`, {
    params: params,
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  return response.data;
}
```

---

## 七、注意事项

1. **认证**: 所有接口都需要在请求头中携带 JWT Token
2. **权限**: 非管理员用户只能查看和操作本部门的数据
3. **分页**: 列表接口支持分页，注意处理 `next` 和 `previous` 字段
4. **错误处理**: 根据 `code` 字段判断请求是否成功，`message` 字段包含错误信息
5. **时间格式**: 所有时间字段使用 ISO 8601 格式（如：`2024-01-01T10:00:00Z`）
