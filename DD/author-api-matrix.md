# 网易 DD 作者接口矩阵

生产页面：`https://cc.163.com/act/m/daily/uibox-dd/`

API 基址：`https://uiapi.w.163.com`

前端使用 JSON，并启用 `withCredentials: true`；在 DD 客户端中还必须经过 `x-w163-token`、`x-timestamp` 和 NEP signed URL 流程。字段主体来自 `DD/remote/uibox-dd.js` 的生产代码静态分析；文末另行记录受控运行时测试。

## 插件

| 操作 | 方法 | 路径 |
| --- | --- | --- |
| 创建 | POST | `/addon/create` |
| 修改 | POST | `/addon/modify` |
| 删除 | POST | `/addon/delete` |
| 作者列表 | POST | `/addon/addon_list` |
| 详情 | GET | `/addon/detail`、`/addon/detail_v2` |
| 版本列表 | GET | `/addon/addon_versions` |
| 分类 | GET | `/addon/category` |
| 游戏版本 | GET | `/game_versions/list` |
| 资源列表 | GET | `/resource/list` |
| 作者信息 | GET | `/author/detail` |

创建/修改共用的表单字段包括：

```text
game_type, game_versions[], scope, addon_type, name, description,
logo, detail_imgs[], primary_category_id, second_category_ids[],
detail_url, release_type, version, html_desc, update_desc,
share_code_life_type, need_buy, price_fen, buy_life_type,
jump_room, room_id, channel_id, channel_type, sync_room,
creation_statement, with_associate, associated_acts[],
need_anchor_vip, vip_levels[]
```

不存在 `sn` 时调用 `/addon/create`；已有条目调用 `/addon/modify`，请求体增加 `sn`。

## 配置分享

| 操作 | 方法 | 路径 |
| --- | --- | --- |
| 列表 | GET | `/share/list` |
| 创建 | POST | `/share/create` |
| 修改 | POST | `/share/modify` |
| 删除 | POST | `/share/delete` |
| 详情 | GET | `/share/detail` |
| 版本详情 | GET | `/share/version/detail` |

前端表单状态包含以下扁平字段，但线上提交前会重建为嵌套的
`known_addon/unknown_addon/wtf/material/font/known_wa/unknown_wa` 对象：

```text
scope, backup_sn, desc, update_desc, title, brief_desc, display_imgs[],
known_addon_items[], known_addon_inner_version{},
unknown_addon_items[], unknown_addon_inner_version{}, wtf_items[],
material_items[], material_inner_version{}, font_items[],
font_inner_version{}, known_wa_items[], known_wa_inner_version{},
unknown_wa_items[], unknown_wa_inner_version{}, share_code_life_type,
need_buy, price_fen, buy_life_type, jump_room, room_id, channel_id,
channel_type, sync_room, creation_statement, with_associate,
associated_acts[], need_anchor_vip, vip_levels[], enable_dd_setup_wizard,
retail_config / retail_ui_config
```

不存在分享标识时调用 `/share/create`；更新调用 `/share/modify`，请求体增加 `share_sn`。

## WA / 字符串

| 操作 | 方法 | 路径 |
| --- | --- | --- |
| 创建 | POST | `/wa/create` |
| 修改 | POST | `/wa/modify` |
| 删除 | POST | `/wa/delete` |
| 详情 | GET | `/wa/detail` |
| 列表 | GET | `/wa/list` |
| 分类 | GET | `/wa/categories` |

提交字段包括：

```text
game_type, scope, name, game_version, brief_desc, display_imgs[],
category_ids[], content, desc, update_desc, version, file_install_path,
with_file, file_path, share_code_life_type, need_buy, price_fen,
buy_life_type, jump_room, room_id, channel_id, channel_type, sync_room,
creation_statement, with_associate, associated_acts[], need_anchor_vip,
vip_levels[], parse_wa_uid, parse_wa_id
```

修改时增加 `sn`。

## 文件上传

上传不是直接把二进制 POST 给业务接口：

1. `GET /file/upload`，传 `file_type`、`file_name`、`business_id`、`mime_type`。
2. 响应给出临时上传 `url`、公开下载地址 `d_url` 和 `maxSize`。
3. 对临时 URL 执行 PUT，带正确 `Content-Type` 和 `X-Amz-Acl: public-read`。
4. 业务表单保存 `d_url`。

插件 ZIP 在前端使用的元数据为：

```json
{
  "file_type": "a19-ui-res",
  "file_name": "addon.zip",
  "business_id": "addon",
  "mime_type": "application/x-zip-compressed"
}
```

## 频道关联辅助接口

生产前端还使用以下接口列出作者可关联的空间/频道：

```http
GET https://api.cc.163.com/v1/mixteammsgproxy/channelList?source=pluginPublish
Authentication: <jwt>
```

空间详情使用：

```http
GET https://api.cc.163.com/v1/mixteammgr/getTeamInfo?teamId=<internal teamId>
```

完整的字段来源、读改写流程、嵌套转换和条件清空规则见
`DD/author-field-coverage.md`。该文档优先于本页的摘要字段列表。

## 真实写入状态

- 六个 create/modify 端点均已使用完整 builder 返回 `code=0`。
- 插件 ZIP 上传授权和 PUT 已成功，业务 create 使用了返回的 `d_url`。
- 配置和 WA 修改可从详情回读；插件测试条目仍在审核，不能宣称新版本已公开。
- 页面字段集合不等于每个字段都必填，其他游戏类型仍需按各自选项验证。

## 无头签名实测

在 DD 自带 Python 运行时中，`NepWrapper` 与客户端随附的 `UiApiClient` 已
完成作者登录（`/login/dflogin`）和服务器时间获取。以下六个端点的 POST
签名均生成成功，且探针记录 `request_sent=false`：

```text
/addon/create   /addon/modify
/share/create   /share/modify
/wa/create      /wa/modify
```

早期签名验证只证明 transport 可用；其后通用字典探针的 3 次插件请求曾返回
HTTP 422。最终改用三套完整 builder 后，六个写端点均返回 `code=0`，插件上传也
端到端成功。完整证据和必须先 GET 的依赖见 `author-crud-verification.md`。

同一组验证已在稳定独立设备 sidecar 与 GUI DD 并存时重复通过：作者登录、服务器
时间及六个 POST 签名全部成功，所有记录均为 `request_sent=false`。作者 transport
因此可以直接纳入方案 A，不依赖 GUI WebView 或进程注入。
