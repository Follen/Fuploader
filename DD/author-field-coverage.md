# DD 作者接口完整字段与读改写流程

调研日期：2026-07-30 至 2026-07-31

## 核心结论

客户端作者入口对插件、配置分享和 WA/字符串都只有两类写动作：

| UI 动作 | 插件 | 配置分享 | WA/字符串 |
| --- | --- | --- | --- |
| 发布新的 | `POST /addon/create` | `POST /share/create` | `POST /wa/create` |
| 编辑已有 | `POST /addon/modify` + `sn` | `POST /share/modify` + `share_sn` | `POST /wa/modify` + `sn` |

不存在单独的 `publish-new-version` API。版本更新仍走 `modify`，版本字段属于完整
表单的一部分。

三个 `modify` 都不能实现成 PATCH。当前前端采用完整的 read-modify-write：

```text
GET 列表/详情
 -> GET 选项字典、频道、会员、云备份和关联内容
 -> 把详情转换成表单状态
 -> 修改目标字段
 -> 执行条件清空、价格换算和嵌套结构重建
 -> NEP 签名完整 JSON
 -> POST modify
 -> GET 详情/列表复核
```

## 公共读取依赖

| 数据 | 接口/来源 | 用途 |
| --- | --- | --- |
| 作者登录 | `GET /login/dflogin` | 获取 `x-w163-token`，仅保留内存 |
| 服务时间 | `GET /server/ts` | 生成 `x-timestamp` 和 NEP 签名参数 |
| 游戏类型 | `GET /game_type/list` | `game_type` 及游戏切换 |
| 游戏版本 | `GET /game_versions/list?game_type=...` | 插件 `game_versions`、WA `game_version` |
| 插件分类 | `GET /addon/category` | 主分类和子分类 |
| WA 分类 | `GET /wa/categories?game_type=...` | `category_ids` |
| 服务/分享有效期 | `GET /act/life_type_cfgs?game_type=...` | `share_code_life_type`、`buy_life_type` |
| 会员等级 | `GET /anchor_vip/level/list?enrich_acts=false` | `vip_levels` |
| 可关联频道 | CC API `GET /v1/mixteammsgproxy/channelList?source=pluginPublish` | `room_id/channel_id/channel_type`；使用频道 JWT |
| 可关联作者内容 | `/addon/addon_list`、`/share/list`、`/wa/list` | `associated_acts` |
| 上传授权 | `GET /file/upload` | 返回 PUT URL 和最终 `d_url` |

编辑前还必须按类型读取：

- 插件：`GET /addon/detail_v2?sn=...`，必要时兼容 `/addon/detail`。
- 配置分享：`GET /share/detail?sn=...`，再读取其 `backup_sn` 对应的
  `GET /backup/detail?sn=...`。
- WA/字符串：`GET /wa/detail?sn=...`。

## 插件字段

当前前端提交以下完整字段；编辑请求最后增加 `sn`。

| 字段 | 来源 | 规则/转换 |
| --- | --- | --- |
| `game_type` | 游戏类型 | 提交时使用当前游戏类型 |
| `game_versions[]` | `/game_versions/list` | 必选，允许多选 |
| `scope` | `public/private` 页签 | 影响有效期、会员和频道同步 |
| `addon_type` | 单体/整合选择 | `0` 单体，`1` 整合 |
| `name` | 表单/详情 | 必填，前端最多 80 字符 |
| `description` | 表单/详情 | 必填，短介绍，前端最多 80 字符 |
| `logo` | 图片上传 | 必填，保存最终 `d_url` |
| `detail_imgs[]` | 图片上传 | 必填，最多 8 张，每张不超过 10 MiB |
| `primary_category_id` | `/addon/category` | 必填 |
| `second_category_ids[]` | `/addon/category` 子项 | 主分类有子项时必须选择；编辑入口会移除详情数组末尾的汇总项再回填 |
| `detail_url` | 插件 ZIP 上传 | 编辑时由 `latest_version.file_path` 映射，不是详情顶层字段 |
| `release_type` | 正式/公测/内测 | `1/2/3` |
| `version` | 表单；编辑时来自 `latest_version.version` | 完整版本号字符串，前端最多 80 字符 |
| `html_desc` | 富文本表单 | 必填，插件详情 |
| `update_desc` | 富文本表单 | 必填，更新公告，前端上限 1000 字符 |
| `share_code_life_type` | `/act/life_type_cfgs` | 公开发布强制 `forever`；私密且免费时使用 |
| `need_buy` | 付费方式 | 一次性付费开关 |
| `price_fen` | 价格输入 | UI 使用元，提交前 `round(value * 100)` |
| `buy_life_type` | `/act/life_type_cfgs` | 付费服务有效期 |
| `jump_room` | 是否关联房间 | `false` 时清空全部房间/频道字段 |
| `room_id` | 频道列表 `teamId` | `jump_room=true` 时必填 |
| `channel_id` | 频道列表 `channelId` | 可为空，取决于选择层级 |
| `channel_type` | 频道列表 `channelType` | 与 `channel_id` 成组 |
| `sync_room` | 更新同步开关 | 私密或未关联房间时强制 `false` |
| `creation_statement` | 固定枚举 | `original/chinesize/renovate/second`，必填 |
| `with_associate` | 是否关联其他内容 | `false` 时清空 `associated_acts` |
| `associated_acts[]` | 作者自己的插件/配置/WA 列表 | 元素只提交 `{sn, act_type}`；开启时至少一项 |
| `need_anchor_vip` | 会员付费开关 | 私密发布强制 `false` |
| `vip_levels[]` | `/anchor_vip/level/list` | 会员付费开启时使用；私密发布清空 |
| `sn` | 插件详情 | 仅 `/addon/modify` 增加 |

插件 ZIP 上传使用：

```text
file_type=a19-ui-res
business_id=addon
file_name=addon.zip
mime_type=application/x-zip-compressed
```

图片上传默认使用 `file_type=a19-ui-media`、`business_id=img`。上传流程均为
`GET /file/upload -> PUT signed URL -> 保存 d_url`。

## 配置分享字段

配置分享是三类中最复杂的一类。`game_type` 用来筛选云备份，但当前前端不把它
直接放进 `/share/create|modify` 请求；服务端通过 `backup_sn` 确定游戏和源数据。

### 前置读取

1. `GET /backup/list` 获取云备份选项并按当前 `game_type` 过滤。
2. 选择 `backup_sn` 后调用 `GET /backup/detail?sn=...`。
3. 从备份详情取得已知/未知插件、WTF 账号角色、材质、字体、已知/未知 WA，
   以及正式服的 `retail_ui_config`。
4. 编辑已有分享时，再用 `/share/detail` 的当前选择与 `inner_version` 回填表单。
5. 没有云备份时，客户端先走独立的云备份流程：`/backup/pre_create`、本地扫描与
   上传、`/backup/finish_create`；这不是 `/share/create` 可以替代的步骤。

### 配置创建/编辑的全部可选项

| UI 选择 | 数据来源 | 写入结果/条件 |
| --- | --- | --- |
| 公开/私密 | 固定页签 | `scope`；私密禁用会员和房间同步 |
| 云端备份 | `/backup/list` | `backup_sn`；切换后清空全部内容选择 |
| 已知插件 | `/backup/detail.known_addon.items` | `known_addon`；选择插件时必须同时选择 WTF |
| 未知插件 | `/backup/detail.unknown_addon.items` | `unknown_addon`；选择插件时必须同时选择 WTF |
| WTF 账号/服务器/角色 | `/backup/detail.wtf.accounts` | 重建 `wtf.accounts[].servers[].items[]` |
| 材质 | `/backup/detail.material.items` | `material` |
| 字体 | `/backup/detail.font.items` | `font` |
| 已知 WA | `/backup/detail.known_wa.items` + 所选账号映射 | `known_wa`；当前 `game_type=10001` UI 隐藏 |
| 未知 WA | `/backup/detail.unknown_wa.items` + 所选账号映射 | `unknown_wa` 并补 `id`；当前 `game_type=10001` UI 隐藏 |
| 编辑模式 | 正式服备份 `retail_ui_config.editMode` | 最多 5 个，写入 `edit_mode` 并指定默认项 |
| 冷却管理器 | 正式服备份 `retail_ui_config.coolDown` | 每个 `spec_tag` 最多一个，写入 `cool_down` |
| DD 配置安装向导 | 表单开关 | `retail_ui_config.enable_dd_setup_wizard`，缺省 `true` |
| 展示图片 | `/file/upload` + PUT | `display_imgs[]`，1-8 张 |
| 免费/付费 | 固定选择 | 付费组可同时选一次性付费和会员，分别写 `need_buy`、`need_anchor_vip` |
| 一次性价格/服务有效期 | 输入 + `/act/life_type_cfgs` | `price_fen`、`buy_life_type` |
| 私密分享码有效期 | `/act/life_type_cfgs` | 私密免费时写 `share_code_life_type` |
| 会员等级 | `/anchor_vip/level/list` | `vip_levels[]`；会员付费开启时使用 |
| 创作声明 | 固定枚举 | `original/chinesize/renovate/second` |
| 关联其他内容 | 自己的插件/配置/WA 列表 | `with_associate` + `{sn,act_type}[]` |
| 关联房间/频道 | CC `channelList` | `jump_room/room_id/channel_id/channel_type` |
| 更新同步频道 | 固定开关 | `sync_room`；仅公开且已关联房间时可用 |
| 本次增量更新 | 编辑页当前全量选择 | 只影响对应 `inner_version` 是否递增；创建页没有此层 |

注意，wire 对象始终包含七组内容容器，不代表 UI 在所有游戏类型都开放七组选择；
builder 必须按当前 `game_type` 和备份实际内容校验可选性。

### 表单状态到线上请求

表单内部使用扁平的 `*_items`，线上请求必须重建为嵌套对象：

| 表单字段 | 线上字段 | 转换 |
| --- | --- | --- |
| `known_addon_items[]` | `known_addon.items[]` | 按 `addon_id` 从备份详情取完整对象 |
| `known_addon_inner_version{}` | `known_addon.inner_version{}` | 新项默认 1；编辑时依据原选择递增 |
| `unknown_addon_items[]` | `unknown_addon.items[]` | 按名称从备份详情过滤 |
| `unknown_addon_inner_version{}` | `unknown_addon.inner_version{}` | 与已知插件相同 |
| `wtf_items[]` | `wtf.accounts[]` | 按 account -> server -> role 三级分组 |
| `material_items[]` | `material.items[]` | 按材质名称取完整对象 |
| `material_inner_version{}` | `material.inner_version{}` | 新项默认 1，编辑时维护版本 |
| `font_items[]` | `font.items[]` | 字体名称数组 |
| `font_inner_version{}` | `font.inner_version{}` | 新项默认 1，编辑时维护版本 |
| `known_wa_items[]` | `known_wa.items[]` | 按 WA `uid` 取完整对象 |
| `known_wa_inner_version{}` | `known_wa.inner_version{}` | 新项默认 1，编辑时维护版本 |
| `unknown_wa_items[]` | `unknown_wa.items[]` | 按 WA `uid` 取完整对象，并用所选 WTF 账号的映射补 `id` |
| `unknown_wa_inner_version{}` | `unknown_wa.inner_version{}` | 新项默认 1，编辑时维护版本 |
| `retail_config` | `retail_ui_config` | 仅正式服；见下方说明 |
| `enable_dd_setup_wizard` | `retail_ui_config.enable_dd_setup_wizard` | 不作为顶层字段提交 |

切换 `backup_sn` 会清空所有内容选择。切换 WTF 账号也会清空已知和未知 WA，
因为 WA 的 `uid -> id` 映射依赖具体账号。

配置请求的顶层和嵌套结构固定如下。这里的 `...完整备份对象` 不是省略实现字段，
而是明确要求从 `/backup/detail` 保留该对象的全部字段；不能建立只挑名称或 ID 的
白名单，否则会丢失服务端恢复配置所需的元数据。

```text
{
  backup_sn, scope, title, brief_desc, desc, update_desc, display_imgs,
  known_addon:   { items: [{...完整备份对象}], inner_version: {...} },
  unknown_addon: { items: [{...完整备份对象}], inner_version: {...} },
  wtf: { accounts: [{ name, servers: [{ name, items: [role] }] }] },
  material:      { items: [{...完整备份对象}], inner_version: {...} },
  font:          { items: [fontName], inner_version: {...} },
  known_wa:      { items: [{...完整备份对象}], inner_version: {...} },
  unknown_wa:    { items: [{...完整备份对象, id}], inner_version: {...} },
  retail_ui_config?: { edit_mode, cool_down, enable_dd_setup_wizard },
  share_code_life_type?, need_buy, price_fen, buy_life_type,
  jump_room, room_id, channel_id, channel_type, sync_room,
  creation_statement, with_associate, associated_acts,
  need_anchor_vip, vip_levels,
  share_sn? // 仅 modify
}
```

`inner_version` 不是普通资源版本号。前端先从编辑详情回填旧 map，再以当前
`/backup/detail` 的全部候选项重建 map：没有旧值的键置为 `1`；编辑时，仅对
“本次增量更新”勾选的键在旧值存在时加 `1`。因此需要同时保存“全量选择”和
“本次更新选择”，不能只拿最终勾选数组推导版本。

### 线上完整字段

| 字段 | 来源 | 规则/转换 |
| --- | --- | --- |
| `backup_sn` | `/backup/list` | 必填，是所有配置内容的根来源 |
| `scope` | `public/private` 页签 | 控制有效期、会员和同步 |
| `title` | 表单/详情 | 必填，前端最多 40 字符 |
| `brief_desc` | 表单/详情 | 必填，前端最多 50 字符 |
| `desc` | 富文本表单 | 必填 |
| `update_desc` | 富文本表单 | 提交；当前前端没有单独的非空校验 |
| `display_imgs[]` | 图片上传 | 至少 1 张，最多 8 张，每张不超过 10 MiB |
| `known_addon` | 备份详情 + 当前选择 | `{items, inner_version}` |
| `unknown_addon` | 备份详情 + 当前选择 | `{items, inner_version}` |
| `wtf` | 当前角色选择 | `{accounts:[{name,servers:[{name,items:[role]}]}]}` |
| `material` | 备份详情 + 当前选择 | `{items, inner_version}` |
| `font` | 备份详情 + 当前选择 | `{items, inner_version}` |
| `known_wa` | 备份详情 + 当前账号 WA | `{items, inner_version}` |
| `unknown_wa` | 备份详情 + 当前账号 WA | `{items, inner_version}` |
| `retail_ui_config` | 正式服备份扩展 | 可选，包含 `edit_mode`、`cool_down`、`enable_dd_setup_wizard` |
| `share_code_life_type` | `/act/life_type_cfgs` | 私密且免费时必填；公开时不使用 |
| `need_buy` | 付费方式 | 一次性付费开关 |
| `price_fen` | 价格输入 | UI 使用元，提交前乘 100；UI 范围 0 或 0.1-200 元 |
| `buy_life_type` | `/act/life_type_cfgs` | 付费时必填，缺省 `seven_day` |
| `jump_room` | 是否关联房间 | `false` 时清空房间/频道字段 |
| `room_id` | 频道列表 `teamId` | 关联房间时必填 |
| `channel_id` | 频道列表 `channelId` | 可选具体频道 |
| `channel_type` | 频道列表 `channelType` | 与频道 ID 成组 |
| `sync_room` | 更新同步开关 | 私密或未关联房间时强制 `false` |
| `creation_statement` | 固定枚举 | 必填 |
| `with_associate` | 是否关联其他内容 | `false` 时清空 `associated_acts` |
| `associated_acts[]` | 作者内容列表 | `{sn, act_type}`；开启时至少一项 |
| `need_anchor_vip` | 会员付费开关 | 私密分享强制 `false` |
| `vip_levels[]` | 会员等级接口 | 会员付费开启时使用，私密分享清空 |
| `share_sn` | 分享详情 | 仅 `/share/modify` 增加 |

当前表单还有两条重要校验：选择任意插件时必须同时选择至少一份 WTF 配置；
并且“分享内容非空”检查只统计插件、WTF、材质和字体，不能只选择 WA。

正式服 `retail_ui_config` 的输入来自备份详情中的驼峰字段 `editMode`、`coolDown`，
线上字段则是 `edit_mode`、`cool_down`。两者都以账号名为对象 key：

- `edit_mode[account][]` 保留扫描结果对象的全部字段，并增加 `is_default`；全账号
  合计最多选择 5 个，选择非空时恰好指定一个默认项。
- `cool_down[account][]` 保留扫描结果对象的全部字段。已知判别字段为 `name`、
  `realm`、`char`、`spec_tag`；UI 按 `spec_tag` 分组，每组最多选一个角色配置。
- `enable_dd_setup_wizard` 是布尔值，缺省按 `true` 提交。
- 只有当前备份含正式服扫描结果且表单持有 `retail_config` 时才提交整个
  `retail_ui_config`；不能把表单辅助字段 `raw/selectedEditMode/selectedCoolDown/
  defaultEditMode` 直接发给服务端。

配置 transport 在 POST 前还会统一归一化：私密分享强制
`sync_room=false/need_anchor_vip=false/vip_levels=[]`；`jump_room=false` 时清空
`room_id/channel_id/channel_type` 并关闭同步；`with_associate=false` 时清空
`associated_acts`。`share_code_life_type` 只在私密请求出现，`buy_life_type` 缺省为
`seven_day`，价格由表单元值按 `100 * value` 转成分。

## WA / 字符串字段

当前前端提交以下完整字段；编辑请求最后增加 `sn`。

| 字段 | 来源 | 规则/转换 |
| --- | --- | --- |
| `game_type` | 当前游戏类型 | 提交时补入 |
| `scope` | `public/private` 页签 | 控制有效期、会员和同步 |
| `name` | 表单/详情 | 必填，前端最多 40 字符 |
| `game_version` | `/game_versions/list` | 必填，单选 |
| `brief_desc` | 表单/详情 | 必填，前端最多 50 字符 |
| `display_imgs[]` | 图片上传 | 必填，最多 8 张，每张不超过 10 MiB |
| `category_ids[]` | `/wa/categories` | 必填，最多 5 项，默认 `ui_original` |
| `content` | 字符串输入 | 必填 |
| `desc` | 富文本表单 | 必填 |
| `update_desc` | 富文本表单 | 必填，前端上限 1000 字符 |
| `version` | 表单/详情 | 仅数字，最多 80 字符；编辑必须严格大于当前版本 |
| `with_file` | 是否关联材质 ZIP | `true` 时要求 `file_path` |
| `file_path` | ZIP 上传 | 保存最终 `d_url` |
| `file_install_path` | 固定枚举 | `Interface/Addons`、`Interface` 或根目录 |
| `parse_wa_uid` | DD 原生 WA 解析 | `content` 以 `!WA:2!` 开头时必须解析得到 |
| `parse_wa_id` | DD 原生 WA 解析 | 与 `parse_wa_uid` 成组；非 WA2 内容清空二者 |
| `share_code_life_type` | `/act/life_type_cfgs` | 公开强制 `forever`；私密免费时使用 |
| `need_buy` | 付费方式 | 一次性付费开关 |
| `price_fen` | 价格输入 | UI 使用元，提交前 `round(value * 100)` |
| `buy_life_type` | `/act/life_type_cfgs` | 付费服务有效期 |
| `jump_room` | 是否关联房间 | `false` 时清空全部房间/频道字段 |
| `room_id` | 频道列表 `teamId` | 关联时必填 |
| `channel_id` | 频道列表 `channelId` | 可选具体频道 |
| `channel_type` | 频道列表 `channelType` | 与频道 ID 成组 |
| `sync_room` | 更新同步开关 | 私密或未关联房间时强制 `false` |
| `creation_statement` | 固定枚举 | 必填 |
| `with_associate` | 是否关联其他内容 | `false` 时清空关联列表 |
| `associated_acts[]` | 作者内容列表 | `{sn, act_type}`；开启时至少一项 |
| `need_anchor_vip` | 会员付费开关 | 私密发布强制 `false` |
| `vip_levels[]` | 会员等级接口 | 会员付费开启时使用；私密发布清空 |
| `sn` | WA 详情 | 仅 `/wa/modify` 增加 |

WA 材质 ZIP 上传参数为：

```text
file_type=a19-ui-res
business_id=wa
file_name=wa_materials.zip
maxFileSize=50 MiB
```

## GET 字段与 POST 字段边界

详情接口返回的对象明显大于提交契约。实现必须按本报告的 wire 字段白名单重建
请求，禁止 `payload = detail; payload.update(changes)`：

- 插件详情中的 `latest_version`、作者、审核、下载统计、订阅状态等均为只读；仅从
  `latest_version.file_path/release_type/version` 映射出表单字段。上传控件使用的本地
  `file_name` 也不进入 `/addon/create|modify`。
- 配置表单的 `game_type`、七组 `*_items`/`*_inner_version`、`retail_config`、
  顶层 `enable_dd_setup_wizard` 都是辅助状态，必须转换成前述嵌套对象；不能原样
  提交。云备份的上传 URL、大小、md5 和任务状态只属于备份流程。
- WA 详情中的作者、审核和统计字段不提交；上传授权的临时 URL 不提交，业务字段
  `file_path` 只保存最终 `d_url`。当前版本比较值是本地校验状态，不是额外字段。
- 三类资源的 `sn/share_sn` 只在 modify 最后补入，create 请求不得携带旧标识。

同理，GET 是 builder 的输入，不是可直接复用的请求体：先获取详情和选项，再转换
为受控表单模型、应用单个修改、校验、重建 wire payload，最后签名。

## 实测状态

- 三类详情、备份和选项 GET 均已运行时确认；六个 create/modify payload 均由独立
  builder 构造并成功签名。
- 插件、配置分享、WA 的 create 和 modify 已全部真实返回 `code=0`。配置和 WA 的
  modify 已从详情回读；插件新版本仍处于审核态，不能把接受提交等同于公开生效。
- 插件文件上传已完成 `/file/upload -> PUT 4,778,463 bytes -> d_url`，PUT 为 200。
- 当前作者清单为 9 项，包含 3 个明确命名的公开测试条目；详见
  `author-crud-verification.md`。
- 早期通用字典探针的 3 次 HTTP 422 保留为反例：签名成功不等于字段完整，后续
  实现必须继续使用本报告的资源专用 builder。

## 实现要求

每种资源建立独立 builder，不共享一个通用 `modify(map)`：

```text
loadOptions()
loadDetail(id)
detailToForm()
applyPatch(userChange)
validateForm()
formToWirePayload()
normalizeConditionals()
signAndPost()
reloadAndVerify()
```

日志只记录端点、返回码、字段缺失名称和目标资源类型；不得记录完整请求体、详情
响应、Cookie、JWT、`x-w163-token` 或 signed URL。
