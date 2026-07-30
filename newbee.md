# 新手盒子上传业务接口与链路

> 整理日期：2026-07-30  
> 客户端版本：NewBeeBox `1.1.17`  
> 范围：已认证之后的创作者业务、WoW 配置云备份及后续 CLI 实现依据。认证、登录、token 获取与刷新不在本文范围内。

## 1. 结论

新手盒子的上传业务分成两套不能混用的流程：

1. **创作者中心发布**：插件、WA/字符串、配置分享和攻略都通过 `https://api.newbeebox.com/creator/...` 接口管理。
2. **桌面端 WoW 配置云备份**：先扫描本地 WoW 目录，把未知插件、WTF、材质和字体上传为云备份，再调用 `/v3/share/create` 保存备份记录。创作者中心的“发布配置”只能引用这个备份的 `cloud_id`，不能直接把任意 ZIP 当成配置发布。

已实机验证插件与配置分享的读取和写入主链路。2026-07-30 的受控线上审计完成了插件创建、插件版本上传、插件元数据编辑与恢复、配置创建、配置元数据更新、配置切换云备份更新。删除、WoW 云备份上传、WA 和攻略写入仍未验证。

## 2. 约定

### 2.1 服务地址

| 用途 | Base URL |
| --- | --- |
| 桌面业务与 Creator API | `https://api.newbeebox.com` |
| 插件分类与游戏版本元数据 | `https://cdn2.newbeebox.com/modconfig.json` |
| 字体/通用对象存储上传服务 | `https://api.next.newbeebox.com/uploadserver` |
| 预签名文件上传 | 接口动态返回的 HTTPS `upload_url` |

除预签名地址的 `PUT` 外，本文发现的业务接口均为 `POST`。普通请求使用 JSON；带文件的 Creator 接口使用 `multipart/form-data`。

### 2.2 已认证 Creator 请求头

调用方已认证时，Creator 请求至少携带：

```http
appId: 6
Authorization: Bearer <resource-token>
token: <author-token>
Accept-Language: zh-CN
```

不要把 token、一次性 code、预签名上传 URL 或用户隐私数据写入日志、配置文件、命令历史和 Git。

### 2.3 返回与错误判断

普通 JSON 接口的成功条件为：

```text
HTTP 2xx 且 response.code == 1
```

错误信息优先读取 `message`，兼容 `error` 和 `error_description`。不能只根据 HTTP 200 判断成功。预签名 `PUT` 在当前客户端实现中要求 HTTP 200。

上传错误必须区分：

- 业务接口失败：保留 HTTP 状态、业务 `code`、`message` 和请求目标 ID。
- 预签名 URL 失败：URL 可能已过期，重新申请 URL 后再传，不能直接重复提交最终业务记录。
- 最终记录创建失败：对象可能已经上传但没有被业务记录引用，应报告为“待清理的孤立对象”，不能盲目重新上传全部内容。

### 2.4 游戏版本与分类

插件分类和游戏版本不能硬编码，当前由公开的 `GET /modconfig.json` 读取。2026-07-30 实测游戏版本如下：

| ID | 名称 |
| ---: | --- |
| 2 | 正式服 |
| 4 | 泰坦重铸 |
| 7 | 熊猫人之谜 |
| 8 | 燃烧的远征 |
| 6 | 经典旧世 |
| 3 | 探索赛季 |

插件版本的 `game_version_list` 是数组，可以同时声明多个版本。配置分享只能引用已有云备份；它的游戏版本由备份 `t_Versionid` 决定，不能在发布时任意改成另一个版本。

## 3. 内容类型

| 内容 | 前端类型 | 菜单 ID | 核心对象 |
| --- | --- | ---: | --- |
| 插件 | `plugin` | 5 | 插件元数据 + 独立版本压缩包 |
| WA/字符串 | `string` | 6 | 单条字符串或字符串集合 + 版本日志 |
| 攻略 | `guide` | 7 | 富文本文章 + 可选附件 |
| 配置分享 | `shareConfig` | 8 | 已有 WoW 云备份的公开/私有发布页 |

## 4. 插件业务

### 4.1 接口清单

| 接口 | 用途 | 验证状态 |
| --- | --- | --- |
| `/creator/wow/mod/publish_list` | 当前作者插件列表 | 实机只读验证 |
| `/creator/wow/mod/permission_check` | 创建/发布权限检查 | 实机写入验证 |
| `/creator/wow/mod/create` | 新建插件元数据 | 实机写入验证 |
| `/creator/wow/mod/publish_detail` | 插件发布详情 | 实机读回验证 |
| `/creator/wow/mod/edit` | 编辑插件元数据、切换公开状态 | 实机写入验证 |
| `/creator/wow/mod/upload_media` | 上传 Logo/截图，字段 `file` | 实机写入验证 |
| `/creator/wow/mod/remove` | 删除插件 | 静态发现，危险操作 |
| `/creator/wow/mod_file/upload_mod_file` | 上传插件版本压缩包 | 实机写入验证 |
| `/creator/wow/mod_file/mod_file_list` | 版本文件列表 | 实机只读验证 |
| `/creator/wow/mod_file/changelog_list` | 更新日志列表 | 静态发现 |
| `/creator/wow/mod_file/get_changelog` | 单条更新日志详情 | 静态发现 |
| `/creator/wow/mod_file/edit_changelog` | 修改更新日志 | 静态发现 |

### 4.2 列表

`POST /creator/wow/mod/publish_list`

```json
{
  "keyword": "",
  "game_version_id": 0,
  "sort_by": "t_last_update",
  "sort_order": "DESC",
  "pagenum": 1,
  "pagesize": 100
}
```

列表位于 `data.list`，总数位于 `data.total`。列表行不稳定地携带最新版本，因此 CLI 应继续查询：

`POST /creator/wow/mod_file/mod_file_list`

```json
{
  "mod_id": 123,
  "game_version_id": 0,
  "pagenum": 1,
  "pagesize": 1
}
```

最新展示版本来自 `data.list[0].t_display_name`。

### 4.3 新建插件

业务顺序：

```text
permission_check
  -> upload_media（Logo/截图，可选）
  -> mod/create（先创建私有元数据）
  -> upload_mod_file（上传首个版本）
  -> mod/edit（需要公开时设置 share_state=1，进入审核）
```

`POST /creator/wow/mod/create` 的主要字段：

| 字段 | 含义 |
| --- | --- |
| `mod_categories` | 插件分类 |
| `content_origin` | 内容来源/原创属性 |
| `content_format` | 详情内容格式 |
| `name` | 插件名称 |
| `description` | 详情正文 |
| `intro` | 简介 |
| `logo` | 已上传媒体地址 |
| `screenshots` | 截图地址集合 |
| `share_state` | 初始通常为 `0`，即不公开 |
| `subscribe_plan_level` | 订阅等级 |
| `link_to_channel` | 关联频道 |

编辑接口字段基本相同，并增加插件 `id`。

实测媒体文件 part 必须携带真实 MIME，例如 PNG 使用 `image/png`；统一发送 `application/octet-stream` 会返回业务 `code=-4`、`上传的文件类型不支持`。

私有插件没有任何版本文件时，调用 `mod/edit` 设置 `share_state=1` 会返回业务 `code=-4`、`需要上传插件文件后才能公开发布`。新建公开插件必须严格按“创建私有元数据 -> 上传首个版本 -> 编辑为公开”的顺序执行。

### 4.4 上传新版本

`POST /creator/wow/mod_file/upload_mod_file`

请求类型：`multipart/form-data`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `mod_id` | number/string | 目标插件 ID |
| `version` | string | 发布版本号 |
| `game_version_list` | JSON string | 游戏版本数组，注意不是普通重复表单字段 |
| `file` | binary | 插件压缩包 |
| `changelog` | string | 更新日志，可选 |
| `link_to_channel` | value | 关联频道，可选 |

前端限制：

- 文件扩展名：`.zip`、`.rar`、`.7z`
- 最大尺寸：300 MB
- 请求超时：10 分钟

CLI 上传前应计算本地 SHA-256、记录文件大小，并先取版本列表检查 `(mod_id, version)` 是否已经存在。未确认服务端覆盖语义之前，同版本默认拒绝重复上传。

### 4.5 更新插件

更新元数据和更新文件是两件事：

- 修改名称、说明、图片、公开状态：`/creator/wow/mod/edit`
- 发布新插件包：`/creator/wow/mod_file/upload_mod_file`
- 只改已有版本日志：先用 `changelog_list/get_changelog` 找记录，再调用 `edit_changelog`

发布新版本不应自动修改公开状态；公开或重新提交审核应作为显式参数。

### 4.6 线上验证记录

- 创建私有审计插件成功：`mod_id=24410`，读回 `t_share=0`、分类 `1031`、Logo 和截图均存在。
- 审计插件尚无版本时提交公开被平台以 `code=-4` 拒绝，读回仍为私有；随后上传正式服版本 `2026.07.30-audit.1`（文件 ID `557459`），再次提交公开成功，首次读回 `t_share=1`、`review_status=0`，即已提交审核而非审核通过。约十秒后该审计对象不再出现在作者列表中，详情接口返回“插件不存在”；这可能是平台对审计内容的异步处理，不能据此声称审核通过或对象仍可访问。
- 在 `AyijeCDM 酒仙专用`（`mod_id=20745`）上传版本 `2026.07.30-audit.1` 成功，随后 `mod_file_list` 可见该版本。
- 临时修改名称、分类、简介、正文、Logo 和截图成功，读回字段一致；随后恢复原名称、分类、正文和媒体成功。
- `upload_mod_file` 与 `mod/edit` 成功时可能返回空对象，必须通过版本列表或详情读回判定最终状态。

## 5. WoW 配置云备份

这一节描述桌面客户端的“上传云端备份”，它是配置分享的前置数据源，不是 Creator 配置发布接口。

### 5.1 接口清单

| 接口 | 用途 | 验证状态 |
| --- | --- | --- |
| `/share/generate_upload_url_v2` | 为单个压缩文件申请预签名 URL | 静态发现 |
| 动态 `upload_url` | `PUT` 上传压缩文件 | 静态发现 |
| `/v3/share/create` | 创建云备份业务记录 | 静态发现 |
| `/v3/share/list` | 查询云备份 | 实机只读验证 |
| `/v3/share/delete` | 删除云备份 | 静态发现，危险操作 |
| `/share/update` | 修改云备份信息；已确认重命名字段 | 静态发现 |

`POST /share/update` 重命名 payload：

```json
{
  "t_id": 123,
  "t_name": "新的备份名称"
}
```

### 5.2 本地扫描范围

客户端并不是把整个 WoW 目录压成一个包，而是拆成五类：

| 类别 | 本地来源 | 上传方式 |
| --- | --- | --- |
| 已知插件 | `Interface/AddOns` 扫描结果与本地 lock 数据 | 不上传插件文件，只记录插件和版本关联元数据 |
| 未知插件 | `Interface/AddOns/<unknown addon>` | 选中的目录统一压缩，预签名 `PUT` |
| WTF | `WTF/Account` | 账户公共配置和每个角色目录分别压缩、分别上传 |
| 材质 | `Interface` 下非 AddOns 内容 | 选中目录统一压缩，预签名 `PUT` |
| 字体 | `Fonts` | `nbb-core` 的 `OssUploader.uploadFolder` |

压缩时 WTF 排除 `*.bak`。临时压缩目录由客户端缓存目录下的 `temp_archive` 承载，提交完成后清理。

### 5.3 申请上传地址

`POST /share/generate_upload_url_v2`

```json
{
  "file_type": "unknown_plug",
  "file_size": 123456
}
```

不同内容使用不同 `file_type`：拆包中至少看到 `unknown_plug`、`material`、`wtfserve`、`wtfrole`。返回关键字段：

```json
{
  "upload_url": "<短期预签名地址>",
  "file_path": "<持久业务引用路径>"
}
```

随后直接：

```http
PUT <upload_url>

<archive bytes>
```

PUT 成功后只把 `file_path` 写入最终 `/v3/share/create` payload，绝不能持久化 `upload_url`。

### 5.4 WTF 上传

对每个选中账户执行：

1. 枚举账户目录下的公共文件和 `SavedVariables`，排除 `*.bak`。
2. 压缩公共配置，申请 `file_type=wtfserve` 的上传地址并 PUT。
3. 将返回 `file_path` 写入该账户的 `commonConfig`。
4. 遍历账户下服务器和角色，每个角色目录单独压缩。
5. 为每个角色申请 `file_type=wtfrole` 的地址并 PUT。
6. 将返回 `file_path` 写入对应角色的 `zip` 字段。

云备份列表中 `wtflist` 项已观察到以下字段：

- `account`
- `account_id`
- `commonConfig`
- `commonConfigFull`
- `commonConfigHash`
- `server`
- `size`
- `editModeLayouts`

服务端返回结构还包含角色树，CLI 应保留未知字段，避免重建对象时丢失服务端扩展数据。

### 5.5 字体上传

字体没有使用 `/share/generate_upload_url_v2`，客户端调用 `nbb-core`：

```text
OssUploader({ apiBase: "https://api.next.newbeebox.com/uploadserver" })
  .uploadFolder({ path: <WoW/Fonts> })
```

成功条件同样为返回 `code == 1`。返回的 `data` 写入最终 payload 的 `font_hash`，字体文件清单写入 `t_font_list`。

CLI 第一版如果不加载客户端原生 `nbb-core`，应明确不支持字体上传，不能用普通 ZIP 上传冒充该链路。

### 5.6 创建云备份记录

所有选中内容上传完成后调用：

`POST /v3/share/create`

初始 payload 结构：

```json
{
  "knowplug_list": [],
  "t_unKnown_list": [],
  "t_font_list": [],
  "t_material_list": [],
  "t_WTF_list": [],
  "versionid": null,
  "wtfconfig": null,
  "unknown_plug": null,
  "material": null,
  "font": null,
  "font_hash": null,
  "wtf": []
}
```

字段关系：

- `versionid`：当前 WoW 游戏版本 ID。
- `unknown_plug`：未知插件压缩包上传后的 `file_path`。
- `material`：材质压缩包上传后的 `file_path`。
- `font_hash`：字体文件夹上传结果。
- `wtf`：包含已写入公共配置和角色 ZIP 路径的账户数组。
- `t_*_list`：对应内容的文件/扫描清单，用于展示和恢复。
- 未选中的类别保持空数组或 `null`，不要填伪造路径。

`knowplug_list` 每项结构：

```json
{
  "name": "AddonName",
  "id": 123,
  "fileName": "addon.zip",
  "fileUrl": "<server file reference>",
  "mod_file_id": 456,
  "mod_version": "1.2.3",
  "display_name": "1.2.3",
  "updateType": 1
}
```

其中 `mod_file_id`、`mod_version`、`display_name`、`updateType` 来自本地 WoW lock 数据与服务端已知插件的匹配结果。不要用最新线上版本替代用户本地实际安装版本。

### 5.7 云备份列表返回

`POST /v3/share/list` 的 `data` 已实机观察为嵌套数组：

```text
Array<Array<backup>>
```

不能假设 `data` 是普通对象或扁平列表。备份对象已观察到：

- `t_id`
- `t_name`
- `t_check`
- `t_Known_plug`
- `t_unKnown_plug`
- `t_unKnown_list`
- `t_WTFconfig`
- `t_WTF_list`
- `t_material`
- `t_material_list`
- `t_font`
- `t_font_hash`
- `t_font_list`
- `t_Versionid`
- `t_create_time`
- `wtflist`

部分 `t_*_list` 字段可能是 JSON 字符串，使用前需要判型并解析，不能默认已经是数组。

## 6. 配置分享发布

### 6.1 接口清单

| 接口 | 用途 | 验证状态 |
| --- | --- | --- |
| `/creator/wow/share/list` | Creator 页面选择可发布的云备份 | 实机只读验证 |
| `/creator/wow/share_config/publish_list` | 已发布配置列表 | 实机只读验证 |
| `/creator/wow/share_config/details_aps` | 配置发布详情 | 实机读回验证 |
| `/creator/wow/share_config/release` | 首次发布配置 | 实机写入验证 |
| `/creator/wow/share_config/update` | 更新配置发布信息/引用 | 实机写入验证 |
| `/creator/wow/share_config/upload` | 上传封面/正文图片，字段 `file` | 实机写入验证 |
| `/creator/wow/share_config/delete` | 删除配置发布 | 静态发现，危险操作 |

`/creator/wow/share/list` 与桌面端 `/v3/share/list` 不是同一个接口：前者是 Creator 选择器使用的视图，后者是桌面云备份管理接口。

### 6.2 列表

`POST /creator/wow/share_config/publish_list`

```json
{
  "keyword": "",
  "game_version_id": 0,
  "sort": 3,
  "offset": 0,
  "pagesize": 100
}
```

列表位于 `data.list`，总数位于 `data.count`，`offset` 从 0 开始。

### 6.3 首次发布和更新字段

`release` 与 `update` 的主要字段：

| 字段 | 含义 |
| --- | --- |
| `cloud_id` | 必填，已有云备份 ID |
| `title` | 标题 |
| `content` | 详情正文 |
| `content_format` | 正文格式 |
| `intro` | 简介 |
| `pic_url` | 封面或主图地址 |
| `content_origin` | 内容来源 |
| `sharing` | 是否公开 |
| `link_to_channel` | 关联频道 |
| `subscribe_plan_level` | 订阅等级 |
| `price` | 价格，前端按分提交 |
| `time_range` | 有效期/售卖时间范围 |
| `linked_mods` | 备份中已知插件的关联信息 |
| `ignored_unknown_mods` | 明确忽略的未知插件 |
| `ignored_materials` | 明确忽略的材质 |
| `ignored_fronts` | 原前端字段拼写如此，表示忽略的字体项 |
| `roleid` | 角色选择信息 |
| `tid` | 仅更新时，目标发布记录 ID |

`linked_mods` 每项：

```json
{
  "mod_id": 123,
  "mod_name": "AddonName",
  "mod_file_id": 456,
  "mod_version": "1.2.3",
  "display_name": "1.2.3",
  "updateType": 1
}
```

配置图片上传的成功 `data` 与插件媒体不同，实测形态为数组，图片路径取 `data[0].name`。CLI 需要兼容对象/数组响应，但普通输出不得打印未引用媒体地址。

首次发布链路：

```text
creator/wow/share/list
  -> 选择 cloud_id
  -> 解析备份中的已知/未知插件、材质、字体和角色
  -> 用户确认 linked_mods 与 ignored_* 列表
  -> share_config/upload（图片，可选）
  -> share_config/release
```

更新链路：

```text
share_config/details_aps
  -> creator/wow/share/list（需要换备份时）
  -> 重新确认关联和忽略项
  -> share_config/update（携带 tid）
```

CLI 不能静默猜测 `ignored_*`。配置备份可能包含无法识别的插件或本地资源，必须由 manifest 明确选择“关联、包含或忽略”。

### 6.4 详情安全边界

`details_aps` 原始响应包含角色 ZIP 路径、WTF 备份树、哈希和原始插件清单。CLI 的 `config get` 只能输出更新所需的安全字段：

- `id`、`title`、`cloud_id`、`public`、`review_status`
- `content`、`content_format`、`intro`、`picture_urls`、`content_origin`
- `link_to_channel`、订阅/价格/时间字段
- 规范化后的 `linked_mods`、三个 `ignored_*`、`role_id`、`updated_at`

不得输出 `roleobj`、`wtflist`、ZIP 路径、哈希或原始配置内容。

### 6.5 线上验证记录

- 基于云备份 `3571309` 创建私有配置成功；`release` 返回空对象，随后通过未过滤 `publish_list` 回查得到发布 ID `58733`。
- 元数据更新成功，标题/简介/正文改变，图片、58 个插件关联和角色保持不变；更新后 `sharing=1`、重新进入审核。
- 切换到云备份 `3567444` 成功，读回 60 个插件关联、3 个未知插件忽略项和新 `role_id`，其余元数据保持不变。
- 更新成功响应实测为 `data=[]`，不能依赖响应体判断字段是否落库，必须调用 `details_aps` 读回。

## 7. WA/字符串业务

### 7.1 接口清单

| 接口 | 用途 | 验证状态 |
| --- | --- | --- |
| `/creator/wow/wa/mtg_uc_publish_list` | 当前作者 WA/字符串列表 | 实机只读验证 |
| `/creator/wow/wa/detail_aps` | 发布详情 | 静态发现 |
| `/creator/wow/wa/category` | 分类列表；请求字段为 `game_version` | 实机只读验证 |
| `/creator/wow/wa/attachment_install_path_list` | 附件安装路径选项 | 实机只读验证 |
| `/creator/wow/wa/publish` | 首次发布 | 静态发现 |
| `/creator/wow/wa/update` | 更新元数据 | 静态发现 |
| `/creator/wow/wa/update_wa_str` | 发布新字符串版本 | 静态发现 |
| `/creator/wow/wa/get_next_version` | 获取下一版本号 | 静态发现 |
| `/creator/wow/wa/upload_media` | 上传图片，字段 `file` | 静态发现 |
| `/creator/wow/wa/delete` | 删除 WA 发布 | 静态发现，危险操作 |
| `/creator/wow/wa_log/list` | 版本日志列表 | 静态发现 |
| `/creator/wow/wa_log/latest_str_info` | 最新字符串信息 | 静态发现 |
| `/creator/wow/wa_log/delete` | 删除版本日志 | 静态发现，危险操作 |
| `/creator/wow/wa_log/edit` | 编辑版本日志 | 静态发现 |
| `/creator/co_author/search_user`、`list`、`set` | WA 联合作者；set 固定 `content_type=3`，发送 `{user_id,share_percent}` | 静态发现 + 请求序列化测试 |
| `/creator/content_reference/search`、`list`、`set` | WA 关联内容；三者分别使用 `target_types`、`content_type/content_id`、`source_type/source_id` | 静态发现 + 请求序列化测试 |
| `/bannerserver/ShareCode/Set` | WA 分享码，固定 `gameId=1`、`moduleType=3` | 静态发现 + 请求序列化测试 |

### 7.2 列表

`POST /creator/wow/wa/mtg_uc_publish_list`

```json
{
  "keyword": "",
  "game_version_id": 0,
  "sort_by": "t_update_time",
  "sort_order": "DESC",
  "offset": 0,
  "pagesize": 100
}
```

列表位于 `data.list`，总数位于 `data.total`。

分类接口不是 `game_version_id`：前端和实机成功请求均使用 `{ "game_version": 2 }`。发送 `game_version_id` 会返回 `code=-4`、`请选择正确的游戏版本`。附件路径实机返回 AddOns、Interface 和根目录三种选项。

### 7.3 首次发布字段

主要字段：

- `game_version_id`
- `name`
- `intro`
- `description`
- `content_format`
- `thumbnail`
- `images`
- `category_id_list`
- `content_origin`
- `subscribe_plan_level`
- `price`
- `time_range`
- `share_state`
- `link_to_channel`
- `wa_str`
- `wa_str_titles`
- `wa_log`
- `string_mode`
- `attachments`

集合模式中，`wa_str` 是 JSON 数组序列化后的字符串，`wa_str_titles` 是与之平行的标题数组。单条字符串不要套用集合编码。

网页创建/编辑表单把 `category_id_list` 和 `thumbnail` 设为必填。`attachments` 不是 ID 数组；每项字段为 `name`、`install_type`、`install_path`、`value`、`is_compressed` 和可选 `timestamp`。

### 7.4 更新版本

先调用 `/creator/wow/wa/get_next_version`，再调用：

`POST /creator/wow/wa/update_wa_str`

```json
{
  "id": 123,
  "version": "<next version>",
  "wa_log": "更新说明",
  "wa_str": "<single string or serialized collection>",
  "wa_str_titles": [],
  "link_to_channel": null
}
```

元数据更新走 `/creator/wow/wa/update`，字符串版本更新走 `update_wa_str`，两者不应合并为一次不透明操作。

创建/编辑成功后的共创、关联内容和分享码是独立附属步骤。任一步失败时保留已创建的 WA ID，不能重新创建主对象。CLI 不提供 `/creator/wow/wa/delete`、`/creator/wow/wa_log/delete` 或 `/creator/content_draft/*` 的命令。

## 8. 攻略业务

### 8.1 接口清单

| 接口 | 用途 | 验证状态 |
| --- | --- | --- |
| `/creator/wow/guide/publish_list` | 当前作者攻略列表 | 实机只读验证 |
| `/creator/wow/guide/detail_aps` | 攻略详情 | 静态发现 |
| `/creator/wow/guide/category_list` | 分类列表 | 静态发现 |
| `/creator/wow/guide/create` | 创建攻略 | 静态发现 |
| `/creator/wow/guide/edit` | 编辑攻略 | 静态发现 |
| `/creator/wow/guide/upload_media` | 上传正文/封面图片，字段 `file` | 静态发现 |
| `/creator/wow/guide/attachment_type_list` | 附件类型选项 | 静态发现 |
| `/creator/wow/guide/attachment_extract_mode_list` | 附件解压方式选项 | 静态发现 |
| `/creator/wow/guide/upload_attachment` | 上传附件 | 静态发现 |
| `/creator/wow/guide/edit_attachment` | 编辑附件信息 | 静态发现 |
| `/creator/wow/guide/remove_attachment` | 删除附件 | 静态发现，危险操作 |
| `/creator/wow/guide/delete` | 删除攻略 | 静态发现，危险操作 |

### 8.2 列表

`POST /creator/wow/guide/publish_list`

```json
{
  "article_type": 2,
  "category_id": null,
  "game_version_id": 0,
  "keyword": "",
  "sort_by": "date",
  "tag": "",
  "offset": 0,
  "pagesize": 100
}
```

列表位于 `data.list`，总数位于 `data.count`。

### 8.3 创建与附件

创建攻略主要字段：

- `title`
- `content`
- `intro`
- `share_status`
- `subscribe_plan_level`
- `content_origin`
- `tags`
- `cover`
- `category_id`
- `game_version_id`
- `article_type: 2`
- 已上传附件 ID 数组

编辑时增加攻略 `id`。

`/creator/wow/guide/upload_attachment` 使用 `multipart/form-data`：

| 字段 | 说明 |
| --- | --- |
| `type` | 附件类型 |
| `extract_mode` | 解压方式，可选 |
| `display_name` | 展示名称 |
| `allow_download` | 是否允许下载 |
| `file` | 附件二进制 |

攻略创建前应先完成附件上传并收集附件 ID；攻略创建失败时要保留孤立附件信息，供重试或清理。

## 9. 公开、审核与状态

当前列表响应观察到的通用审核映射：

| 审核值 | 含义 |
| ---: | --- |
| `0` | 审核中 |
| `1` | 已通过 |
| `2` | 已拒绝 |

只有内容处于公开状态时审核值才有发布意义；私有内容应显示为“未提交”，而不是把旧审核值误报为当前审核结果。

不同业务的公开字段不一致：

| 内容 | 字段 | 已观察私有值 |
| --- | --- | ---: |
| 插件 | `t_share` / 写入时 `share_state` | `0` |
| WA | `t_share_state` / 写入时 `share_state` | `2` |
| 配置分享 | `t_sharing` / 写入时 `sharing` | `0` |
| 攻略 | `share_state` / 写入时 `share_status` | `0` |

这些值不能抽象成一个全业务通用数字。CLI 内部可以统一为 `private/public`，但序列化时必须使用各业务自己的字段和值。WA 和攻略的写入状态值仍需在首次受控写测试中确认。

任何从私有切到公开的操作都视为“提交审核”，命令必须显示目标 ID、当前状态和预期状态，并要求显式 `--submit-review`。

## 10. 另一套通用分片上传

拆包还发现一套通用游戏云存档/包上传协议：

1. `POST https://api.next.newbeebox.com/uploadserver/Upload/multipart/v2/init`
2. 按顺序 `PUT` 返回的 `presignedUri[]`
3. `POST /uploadserver/Upload/multipart/v2/complete`
4. 再调用对应业务接口保存云存档记录

初始化字段为 `fileSize`、`fileName`；返回包含 `totalChunks`、`chunkSize`、`uploadId`、`key` 和 `presignedUri[]`。客户端对失败分片最多重试三次。

这套协议来自通用游戏云存档模块，**不是**以下两个流程：

- WoW 插件版本：直接调用 `/creator/wow/mod_file/upload_mod_file`
- WoW 配置备份普通 ZIP：调用 `/share/generate_upload_url_v2` 后单次 PUT

实现时不要因为它更通用就替换已确认的 WoW 专用链路。

## 11. CLI 建议

建议命令面：

```text
fuploader newbee addon list|get|create|edit|publish-version|changelog
fuploader newbee backup list|scan|create|rename|delete
fuploader newbee config list|get|release|update|delete
fuploader newbee wa list|get|create|edit|publish-version|delete
fuploader newbee guide list|get|create|edit|delete
```

### 11.1 Manifest

写操作应从项目内 manifest 读取稳定输入，不把大段正文和数组塞进命令行。建议结构：

```yaml
provider: newbee
type: addon
id: 123
metadata:
  name: ExampleAddon
  share: private
release:
  version: 1.2.3
  gameVersions: [1]
  archive: ./dist/ExampleAddon-1.2.3.zip
  changelog: ./CHANGELOG.md
```

配置分享 manifest 还必须显式保存 `cloud_id`、`linked_mods`、`ignored_unknown_mods`、`ignored_materials`、`ignored_fronts` 和角色选择，确保 Agent 每次执行得到相同 payload。

### 11.2 安全默认值

- 写命令收到合法 `--input` 后立即执行；可选 `--dry-run` 只做本地校验，不检查远端权限。
- CLI 不提供删除命令；Fupload Skill 在写入前展示完整计划并取得一次用户确认。
- 插件创建默认私有；`plugin edit` 和 `config update` 固定公开并可能进入审核。
- 日志只记录 token 是否存在，不记录 token 内容。
- 预签名 URL 始终脱敏；最多记录 host、对象类型和过期时间。
- 并发上传设置上限；元数据创建、最终记录创建和公开状态修改保持串行。

### 11.3 幂等与恢复

插件版本建议使用 `(mod_id, version, sha256)` 作为本地幂等键。上传前查询版本列表：

- 版本不存在：上传。
- 版本存在且本地哈希未知：停止并要求人工确认。
- 网络超时但服务端可能已成功：先重新查询版本，不立即重传。

配置备份建议为每次执行生成本地 operation journal，记录：

```text
scan completed
archive path + sha256
upload file_type
returned file_path
final /v3/share/create status
created cloud backup id
```

这样最终记录创建失败时可以判断是否复用已上传对象；在没有确认 `file_path` 有效期前，不自动跨进程长期复用。

## 12. 验证矩阵与待测阻塞点

| 能力 | 当前状态 | 备注 |
| --- | --- | --- |
| 插件列表 | 已实机验证 | 当前账号可读取 |
| 插件最新版本查询 | 已实机验证 | 通过 `mod_file_list` 补查 |
| WA 列表 | 已实机验证 | 当前返回 0 条不代表接口失败 |
| 配置分享列表 | 已实机验证 | 可读取私有与公开记录 |
| 攻略列表 | 已实机验证 | 当前返回 0 条不代表接口失败 |
| Creator 云备份列表 | 已实机验证 | 返回嵌套数组 |
| 插件新建/元数据更新 | 已实机写入验证 | 审计插件 24410；正式插件编辑后已恢复 |
| 插件版本上传 | 已实机写入验证 | AyijeCDM 版本 `2026.07.30-audit.1` |
| 插件版本日志读取/编辑 | 已实机写入验证 | 文件 `557441` 同值编辑并读回成功 |
| WoW 配置云备份上传 | 未写入验证 | 扫描、压缩、PUT 和 create 链路已发现 |
| 配置首次发布/更新 | 已实机写入验证 | 配置 58733；创建、信息更新、换备份均成功 |
| WA 分类/附件路径 | 已实机只读验证 | 分类必须发送 `game_version`；附件路径返回 3 项 |
| WA 创建/更新版本 | 未写入验证 | 当前作者 WA 列表为空；请求字段与调用顺序已有单元测试 |
| 攻略创建/附件上传 | 未写入验证 | 需确认附件创建失败后的清理策略 |
| 删除类接口 | 未验证 | 在隔离测试内容准备好前不调用 |

本轮真实写入发现并回归的阻塞点：

1. multipart 文件 part 使用通用 MIME 会导致图片类型拒绝，必须按扩展名设置 Content-Type。
2. 插件媒体和配置图片的成功响应结构不同，后者使用 `data[0].name`。
3. 配置创建和更新成功响应可能没有 ID/字段，需要 list/get 读回。
4. `details_aps` 原始结构包含不应暴露的备份路径与哈希，必须归一化后输出。
5. 分类和游戏版本会变化，必须从公开元数据动态查询。
6. WA 分类字段是 `game_version`，不是其他内容表单常用的 `game_version_id`。
7. WA 私有状态值为 `2`，不能沿用插件/配置的 `0`。

## 13. 证据位置

拆包与格式化中间产物均在 `newbee/`：

| 文件 | 主要证据 |
| --- | --- |
| `newbee/analysis/creator.pretty.js` | Creator 四类内容接口、表单字段、状态和通用分片上传 |
| `newbee/analysis/2261.pretty.js` | WoW 配置扫描、压缩、上传、最终备份 payload |
| `newbee/analysis/app.pretty.js` | `/v3/share/*` 与 `/share/generate_upload_url_v2` 封装 |
| `newbee/analysis/chunk-common.pretty.js` | `OssUploader` 和通用云存档上传实现 |
| `newbee/analysis/5945.pretty.js` | 配置备份相关页面逻辑 |
| `newbee/FINDINGS.md` | 初期认证与 Creator 调查记录 |
| `newbee/creator-content.mjs` | 已验证的只读 Creator API 封装 |
| `newbee/creator-content.test.mjs` | 列表与状态归一化测试 |

当前 Go 测试覆盖认证、Creator 会话、请求序列化、媒体 MIME、媒体响应差异、详情脱敏、创建 ID 回查和 CLI help。线上验证记录只证明 2026-07-30 当前账号与当前服务版本的行为；后续仍应保留写后读回。
