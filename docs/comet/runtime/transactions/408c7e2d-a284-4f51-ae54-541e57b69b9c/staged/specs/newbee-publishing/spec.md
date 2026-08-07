# NewBee 插件、配置与 WA 完整发布规格

## 会话与公共规则

provider 复用当前用户 NewBeeBox 桌面客户端的 auth-store，按已验证交换链路取得 Creator
会话。凭据只在内存中使用；刷新后的桌面状态只写回客户端自己的存储。业务成功要求 HTTP
2xx 且 `code == 1`。

动态分类和游戏版本从平台元数据查询。三类资源的私有/公开 wire 值分别转换，不能共用一个
数字：插件 `share_state 0/1`，配置 `sharing 0/1`，WA `share_state 2/1`。公开转换是显式
提交审核。

## 插件

插件 create/edit 的完整可写字段为：`mod_categories`、`content_origin`、`content_format`、
`name`、`description`、`intro`、`logo`/本地 logo、`screenshots`/本地截图、`share_state`、
`subscribe_plan_level`、`link_to_channel`；edit 另含 `id`。create 默认私有。

插件 update 只发布新版本，字段为 `mod_id`、`version`、`game_version_list`、`file`、
`changelog`、`link_to_channel`。文件只接受 `.zip/.rar/.7z`、不超过 300 MB，版本列表非空，
上传前查询版本历史并拒绝同版本覆盖。更新不修改插件元数据或公开状态。

edit 先读取详情，以 allowlist 映射所有元数据。未提供字段保持；显式清空仅用于平台允许的
intro/description/screenshots 等字段。私有且没有版本文件时禁止提交公开。已有版本日志通过
独立 list/get/edit 命令读取或修改，日志可显式清空，且不上传版本或修改主对象。

## 配置分享

配置 create 的完整字段为：`cloud_id`、`title`、`content`、`content_format`、`intro`、
`pic_url`/本地图片、`content_origin`、`sharing`、`link_to_channel`、
`subscribe_plan_level`、`price`、`time_range`、`linked_mods`、`ignored_unknown_mods`、
`ignored_materials`、`ignored_fronts`、`roleid`。update/edit 另含 `tid`。

`linked_mods` 每项覆盖 `mod_id`、`mod_name`、`mod_file_id`、`mod_version`、
`display_name`、`updateType`。provider 兼容服务端数组或 JSON 字符串，但安全 get 不输出
ZIP、下载地址、哈希、原始 WTF 或原始配置。

动作拆分如下：

- create：从 Creator 云备份创建发布记录，可设置所有创建期字段，默认私有；
- update：只更换或更新 `cloud_id` 与该备份对应的 `linked_mods`、三个 `ignored_*`、
  `roleid`；必须先读当前详情和目标备份；
- edit：只修改 title/content/content_format/intro/pictures/content_origin、商业、频道和公开
  字段，不更换 cloud_id 或备份选择。

更换 `cloud_id` 时，关联、忽略项和角色必须针对新备份显式提供；不能沿用旧值。任何局部
动作都先读取详情，最终调用真实 release/update endpoint 后以 details_aps 读回。

## WA/字符串

WA create/edit 的元数据字段为：`game_version_id`、`name`、`intro`、`description`、
`content_format`、`thumbnail`/本地封面、`images`/本地图片、`category_id_list`、
`content_origin`、`subscribe_plan_level`、`price`、`time_range`、`share_state`、
`link_to_channel`、`attachments`；edit 另含 `id`。create 的 description、至少一个分类和封面必填。

附件项完整字段为 `name`、`install_type`、`install_path`、`value`、`is_compressed` 和可选
`timestamp`。附件、封面、图片支持平台真实上传链路和媒体引用；安装路径从动态接口读取。

create 另含首次字符串字段 `wa_str`、`wa_str_titles`、`wa_log`、`string_mode`。单条模式
使用原始字符串和空标题数组；合集模式把字符串数组 JSON 序列化，并提供同序标题数组。
update 先调用 `get_next_version`，再用 `id/version/wa_str/wa_str_titles/wa_log/
link_to_channel` 调用 `update_wa_str`；它不修改元数据。edit 调用元数据 endpoint，不能
夹带字符串版本字段。

WA 日志 latest/list/get/edit、媒体上传、共创 search/list/set、引用 search/list/set 和
分享码 set 均为独立原子命令。共创项包含 `user_id/share_percent` 且总比例不超过 1；引用项
包含 `type/id`。附属动作失败不重新创建或更新 WA 主对象。

## 阶段与读回

references 为每个字段记录 create/update/edit 可用性。输入包含错误阶段字段时本地拒绝，
不能静默忽略。所有局部 edit/update 按字段存在性合并；动态分类、版本、附件路径、备份和
当前对象读取失败即停止。每次写入后从资源详情、发布列表、版本列表或日志接口读回关键字段。

最终验收必须使用当前已登录 NewBeeBox 客户端和明确标识的隔离测试对象，对插件、配置、WA
各执行真实 create、update、edit。每个动作成功后立即读回目标详情或版本并核对关键字段；
失败时停止后续动作并记录已创建对象和安全重试入口。测试不修改既有正式对象、不调用
delete，所有保留测试对象的 ID、名称、动作结果和审核状态写入验证报告。

最终验证必须从平台元数据动态枚举当时全部游戏 build，并对每个 build 查询版本、插件分类、
WA 分类、作者列表和云备份分布。build-specific 版本、分类、备份和资源 ID 必须保持隔离，
任何跨 build 复用均在写入前失败。插件、WA 和配置的逐 build 真实写入范围按 brief 中最终
确认策略执行：插件和 WA 覆盖全部动态 build；配置覆盖有云备份的全部 build。探索赛季没有
云备份时不写配置，必须验证工作流正确停止并在报告记录前置条件，不能伪造真实写入结论。

除主资源九条写动作外，session doctor、全部分类/版本/列表/详情、备份详情、媒体上传、WA
日志、共创、引用和分享码等 CLI 暴露接口都必须有生产环境验证结论。验证后继续审计字段阶段、
敏感输出、上传遗留对象、最终一致性和错误恢复，修复后重跑相关真实与回归测试。

公开 NewBee provider/CLI 不提供 delete。全量验证结束后，分发范围之外的 `analyze/` 清理
流程可以调用平台真实删除端点，但只接受验证报告中本次创建且已读回确认的 ID；删除后再次
list/get 确认，不确定结果不得盲目重发或扩大清理范围。

## 官方来源固定与凭据隔离

NewBee 凭据只从 Windows Known Folder 派生的 `NewBeeBox/auth-store` 读取和原子写回；生产
运行不接受认证目录环境覆盖。认证、Creator、next API、metadata 和 uploadserver 只使用内置
官方 HTTPS 地址。任何带凭据、认证 handoff、Creator header 或本地上传内容的请求只允许同
origin 重定向；跨 scheme、host 或 port 在发送敏感数据前拒绝。

`session doctor` 在认证请求前返回/验证脱敏的官方 origin 与 auth-store 来源。环境中出现旧的
`FUPLOAD_NEWBEE_*` endpoint/auth-dir 变量不改变目标，也不能让凭据或文件发往变量指定位置。
