# DD 作者接口真实 CRUD 验证

验证日期：2026-07-30 至 2026-07-31

## 结论

稳定设备 sidecar 已真实打通插件、配置分享、WA/字符串的六个作者写端点。三类
资源均使用独立 allowlist builder，先 GET 详情和选项，再重建完整请求；没有把详情
响应直接透传为 POST。

| 资源 | create | modify | GET 复核 |
| --- | --- | --- | --- |
| 插件 | `/addon/create` `code=0` | `/addon/modify` `code=0` | 条目存在，当前 `status=3`；新版本仍待审核，公开详情尚未切换 |
| 配置分享 | `/share/create` `code=0` | `/share/modify` `code=0` | `/share/detail` 已回读修改公告 |
| WA/字符串 | `/wa/create` `code=0` | `/wa/modify` `code=0` | `/wa/detail` 已回读修改公告和版本 `2` |

本次还完整验证了插件文件上传：下载源插件 ZIP 后，通过 `GET /file/upload` 获取新
上传授权，在内存中 PUT 4,778,463 字节，返回 HTTP 200，并把新的 `d_url` 用于
`/addon/create`。signed URL、源文件和响应正文均未落盘。

## 公开测试条目

| 资源 | 名称 | 标识 | 当前状态 |
| --- | --- | --- | --- |
| 插件 | `RememberNoob [Fupload-addon-0730235414]` | `f18a4f03c3364e7da66aa67af03c83d0` | `status=3`，列表显示版本 `1.0.3`；modify 提交的 `1.0.4` 待审核 |
| 配置分享 | `自用配置哦 [Fupload-config-0730235724]` | `81318c6fd9cf4fc28edcc0fbdc60a67f` | `not_ready`，modify 已可从详情回读 |
| WA/字符串 | `提高性能 [Fupload-WA-0730235954]` | `4e53e8001f3b4e53a1870a97c51577e0` | `not_ready`，详情版本 `2` |

验证后作者清单共 9 项：原有 4 个插件、1 个配置、1 个 WA 加上述 3 个测试条目。
没有调用 delete，也没有修改三个源条目；测试条目保留用于后续审核态和更新流程
复核。

## 必须先 GET 的信息

所有作者请求首先依赖两步会话读取：

| GET/来源 | 必要性 | 产物 |
| --- | --- | --- |
| `GET /login/dflogin` | 所有作者请求必需 | 内存中的 `x-w163-token` |
| `GET /server/ts` | 所有签名请求必需 | `x-timestamp` 和 NEP 签名时间 |
| `AccountCredStorage` + `MobileReLoginFlow` | sidecar 登录必需 | 登录 Cookie/JWT 所需会话，不直接读取明文凭据 |

公共表单选项：

| GET | 提供字段 | 何时必须 |
| --- | --- | --- |
| `/game_type/list` | `game_type` | 创建、切换游戏 |
| `/game_versions/list?game_type=...` | 插件 `game_versions[]`、WA `game_version` | 插件/WA 创建和编辑 |
| `/act/life_type_cfgs?game_type=...` | `share_code_life_type`、`buy_life_type` | 私密免费或一次性付费 |
| `/anchor_vip/level/list?enrich_acts=false` | `vip_levels[]` | 会员付费开启时 |
| CC `/v1/mixteammsgproxy/channelList?source=pluginPublish` | `room_id/channel_id/channel_type` | `jump_room=true` 时；使用频道 JWT |
| 自己的 `/addon/addon_list`、`/share/list`、`/wa/list` | `associated_acts[]` | `with_associate=true` 时 |
| `/file/upload` | PUT URL、`d_url`、`maxSize` | 新上传图片、插件 ZIP 或 WA 材质 ZIP |

插件 read-modify-write：

| GET | 用途 |
| --- | --- |
| `/addon/detail_v2?sn=...`，必要时 `/addon/detail` | 回填全部可编辑字段；`latest_version.file_path/release_type/version/game_versions` 必须映射到提交字段 |
| `/addon/category` | 校验 `primary_category_id/second_category_ids[]`，不能只复用详情数组 |
| `/addon/addon_versions?sn=...&game_type=...&page=...` | 已发布版本列表；待审核新条目可能暂时返回空列表 |

配置分享 read-modify-write：

| GET | 用途 |
| --- | --- |
| `/share/detail?sn=...` | 当前全量选择、旧 `inner_version`、付费/频道/关联字段 |
| `/backup/list` | 按 `game_type` 选择 `backup_sn` |
| `/backup/detail?sn=<backup_sn>` | 已知/未知插件、WTF、材质、字体、WA、正式服 `editMode/coolDown` 的完整源对象 |

配置不能只 GET `/share/detail` 后改标题。builder 必须用 `/backup/detail` 验证当前
选择、补全对象、重建七组 `{items,inner_version}`、WTF 三级分组和
`retail_ui_config`。编辑时还要保存“本次增量更新”选择，用它决定哪些
`inner_version` 加一。

WA/字符串 read-modify-write：

| GET/来源 | 用途 |
| --- | --- |
| `/wa/detail?sn=...` | 回填内容、分类、版本、图片、材质和公共商业字段 |
| `/wa/categories?game_type=...` | `category_ids[]`，最多 5 项 |
| `/game_versions/list?game_type=...` | `game_version` |
| DD 原生 WA 解析 bridge | 内容以 `!WA:2!` 开头且内容变化时重新生成 `parse_wa_uid/parse_wa_id` |

## 实测选项规模

当前账号和 `game_type=10001` 的只读返回为：5 个游戏类型、115 个游戏版本、30 个
插件分类、32 个 WA 分类、2 个有效期选项、1 个云备份。会员等级当前返回 0 项，
因此测试 payload 关闭了会员付费。源插件的 `/addon/addon_versions` 返回 2 个已发布
版本，证明该 GET 的完整参数形状有效。

## 状态与限制

- `code=0` 表示 create/modify 已被作者服务接受，不等于网易审核已经通过。
- 插件测试条目仍为 `status=3`，列表和详情继续展示已提交 create 版本；modify 的
  新版本需等待审核后再确认公开可见性。
- 配置和 WA 的详情已能回读 modify 内容，但列表状态仍为 `not_ready`。
- sidecar 必须单例。一次误并发启动两个同 `clientNo` 的 sidecar 时，第二个会话的
  JWT 获取失败；第一个配置 create 已正常完成，第二个没有发送 WA 请求。串行重跑
  WA 后全部成功，GUI DD 未掉线。
- 早期通用字典探针的 2 次插件 modify 和 1 次 create 曾返回 HTTP 422；这是错误
  builder 的历史反例。改为三套完整 builder 后，六个写端点均返回 `code=0`。

## 可复核实现

- `author_schema_probe.py`：只读输出字段名、类型和数量。
- `author_crud_probe.py`：完整 builder、上传、create/modify、轮询和脱敏错误摘要。
- `author_inventory_probe.py`：只读作者清单复核。

探针日志只允许端点、返回码、字段数量、状态和业务条目标识；不得记录完整 payload、
正文、Cookie、JWT、`x-w163-token` 或 signed URL。
