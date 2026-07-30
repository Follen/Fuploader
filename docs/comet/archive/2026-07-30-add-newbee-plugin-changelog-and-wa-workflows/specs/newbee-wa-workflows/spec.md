# 新手盒子 WA 完整链路

## 目标

覆盖新手盒子 WA（WeakAura/字符串内容）从查询、创建、元数据编辑、字符串新版本到版本日志的全部非删除链路，并让 Skill 能编排共创、关联内容和分享码附属动作。

## CLI 命令

- `wa list`：分页列出当前作者 WA。
- `wa get --id <id>`：读取可编辑详情。
- `wa categories`：读取分类树。
- `wa attachment-paths`：读取可用附件安装路径。
- `wa create --input <path|->`：创建 WA。
- `wa edit --input <path|->`：编辑既有 WA 元数据。
- `wa publish-version --input <path|->`：发布字符串新版本；先获取下一版本号。
- `wa changelog latest --id <id>`：读取最新字符串版本信息。
- `wa changelog list --id <id>`、`wa changelog get --id <id>`、`wa changelog edit --input <path|->`：读取/编辑 WA 版本日志。
- `wa media upload --input <path|->`：显式上传封面/截图媒体并返回媒体引用，不隐式创建 WA。
- `wa co-author search|list|set`、`wa reference search|list|set`、`wa share-code set`：WA 附属非删除动作。

所有写命令支持 `--dry-run`；Skill 始终使用 `--output json`，按原子命令顺序执行并在中途失败时停止。

## 主链路 endpoint 与字段

| 动作 | endpoint | API 必传 | 网页条件必传/可选 |
| --- | --- | --- | --- |
| 列表 | `POST /creator/wow/wa/mtg_uc_publish_list` | `offset`、分页参数按列表组件 | `game_id`、状态/搜索过滤 |
| 详情 | `POST /creator/wow/wa/detail_aps` | `id` | 无 |
| 分类 | `POST /creator/wow/wa/category` | `game_version`（值为游戏版本 ID） | 无 |
| 附件路径 | `POST /creator/wow/wa/attachment_install_path_list` | 无 | 无 |
| 媒体 | `POST /creator/wow/wa/upload_media` | multipart `file` | 文件类型/大小由服务端返回约束 |
| 创建 | `POST /creator/wow/wa/publish` | `game_version_id`、`name`、`content_format`、`wa_str`、`wa_log`、`string_mode`、`share_state`、`content_origin` | `intro`、`description`、`thumbnail`、`images`、`category_id_list`、`subscribe_plan_level`、`price`、`time_range`、`link_to_channel`、`attachments`；付费/订阅/频道/媒体启用时分别必传相关值 |
| 元数据编辑 | `POST /creator/wow/wa/update` | `id` 及要更新的元数据 | 同创建字段的条件字段；字符串字段不在此动作更新 |
| 下一版本 | `POST /creator/wow/wa/get_next_version` | `id` | 无 |
| 字符串新版本 | `POST /creator/wow/wa/update_wa_str` | `id`、`version`、`wa_str`、`wa_log` | `wa_str_titles`（集合时必传数组）、`link_to_channel` |
| 最新字符串信息 | `POST /creator/wow/wa_log/latest_str_info` | `wa_id` 或服务端详情要求的 ID 字段 | 无 |
| WA 日志列表 | `POST /creator/wow/wa_log/list` | `wa_id` 或服务端详情要求的 ID 字段 | 分页字段 |
| WA 日志编辑 | `POST /creator/wow/wa_log/edit` | 日志记录 ID、`wa_log` | 无 |

创建/编辑表单字段使用稳定命名：`game_version_id`、`name`、`intro`、`description`、`content_format`、`thumbnail`、`images`、`category_id_list`、`content_origin`、`subscribe_plan_level`、`price`、`time_range`、`share_state`、`link_to_channel`、`attachments`、`wa_str`、`wa_str_titles`、`wa_log`、`string_mode`。WA 的公开值为 `1`、私有值为 `2`，不得复用插件的私有值 `0`。

网页创建/编辑表单要求至少一个分类和封面。`attachments` 是对象数组，每项为 `name`、`install_type`、`install_path`、`value`、`is_compressed` 和可选 `timestamp`，不是附件 ID 数组。本次输入只接受已经通过平台材质链路取得的远端 `value`，不负责上传本地材质文件。

字符串模式规则：单条模式发送原始 `wa_str` 且 `wa_str_titles: []`；集合模式发送 JSON 数组字符串，并发送同序标题数组。新版本调用顺序固定为 `get_next_version` → `update_wa_str`。

## 附属 endpoint

WA 创建或编辑成功后，Skill 可按用户输入调用：

- `POST /creator/co_author/search_user`、`/creator/co_author/list`、`/creator/co_author/set`，固定 `content_type=3`；set 的 `co_authors` 项为 `{user_id, share_percent}`。
- `POST /creator/content_reference/search` 使用 `target_types:[2]`，`/creator/content_reference/list` 使用 `content_type=2/content_id`，`/creator/content_reference/set` 使用 `source_type=2/source_id`；set 的 `references` 项为 `{type,id}`。
- `POST /bannerserver/ShareCode/Set`，发送 `{gameId: 1, moduleId: <wa_id>, moduleType: 3}`。

这些动作必须是显式 CLI 命令或 Skill 计划中的独立步骤，不得隐藏在创建/编辑请求中；失败时报告已完成的 WA 主动作和未完成附属动作。

## 输入 schema 示例

```yaml
schema: fupload.newbee.wa.publish-version.v1
id: 123
version: "1.0.1"
wa_log: "修复触发条件"
string_mode: single
wa_str: "!WA:2!..."
wa_str_titles: []
link_to_channel: false
```

创建与元数据编辑输入必须包含相应 schema 版本；媒体字段只能引用已上传媒体返回的 ID/URL。合集由调用方提供字符串数组的 JSON 文本与同序标题数组。未知字段、缺少 API 必传字段或条件字段不完整时不发请求。

## 非目标与安全

- 不调用 `/creator/wow/wa/delete`、`/creator/wow/wa_log/delete`。
- 不调用 `/creator/content_draft/*`，不提供草稿保存、恢复或草稿发布。
- 不上传本地 WA 材质文件，不提供合集条目对象输入，也不穷举发布页全部设置的枚举与组合校验；这些能力属于后续 change。
- 不把审核中描述为审核通过；更新公开状态的结果按服务端状态原样输出。
- 不在输出中暴露原始字符串、凭据、下载 URL 或预签名 URL；需要审计时只输出长度、哈希或脱敏摘要。

## 验收

- 五类主操作（查询、创建、元数据编辑、字符串新版本、日志管理）均有原子 CLI 和详尽 help。
- 创建、编辑、新版本和日志编辑的请求字段与前端链路一致；单条/集合字符串分别按规则序列化。
- 媒体上传、共创、关联内容、分享码均可单独重试，不会重复创建主对象。
- 真实登录态下列表/详情/分类/版本号/日志读取成功；写入测试记录 HTTP 与业务 code，失败时不执行后续步骤。
