# Outcome

审计并修复 NewBeeBox 与 DD 的平台契约错配，确保动态选项使用正确的业务值、写入后的读回能证明关键字段已落库；同时为 Skill 与 Python CLI 增加插件、配置和 WA 主记录的显式删除工作流。

# Scope

- 双平台插件、配置、WA 的 create/update/edit/delete 参数类型、动态选项、条件字段、序列化、错误处理和读回。
- NewBeeBox 插件版本 build 字符串与父分支 ID 的区分，以及上传后版本绑定验证。
- Skill 文档、CLI help/schema、provider 删除入口和针对删除的读回验证。
- 认证、DD sidecar、上传 API 和已存在发布流程的回归测试。

# Non-goals

- 不删除现有线上对象，不重传用户给出的 ZIP，不修改审核状态。
- 不实现 GUI 自动化、草稿、消息或后台管理功能。
- 不支持 DD 或 NewBeeBox 的单独版本文件删除；只删除用户确认的单个主记录。

# Acceptance examples

- NewBeeBox `plugin update` 使用 `game_version_list: ["3.80.2"]` 发送，并拒绝父分支整数 ID；上传成功但版本列表没有绑定 build 时返回失败证据，而不是成功。
- DD 插件、配置、WA 的动态 build、分类、频道、关联和商业枚举在写入前都按当前响应校验，任何错误值在本地停止。
- `newbee` 和 `dd` 均能通过 Skill/CLI help 暴露 `plugin delete`、`config delete`、`wa delete`；删除前后均有明确 readback，缺少确认或目标不匹配时不写入。
- 双平台既有 create/update/edit 流程和完整认证回归不退化。

# Constraints and invariants

- 所有动态 ID、build、分类、频道、关联和 DD 枚举必须来自实时接口或当前对象，不硬编码业务选项。
- 写入前完成 GET/选项读取；写入后立即 GET/list/versions 验证关键字段。
- 删除是不可逆业务动作，必须要求独立显式确认参数，并限制为用户明确指定的单个主记录。
- 不输出或持久化 token、Cookie、JWT、签名 URL、DD clientNo、原始 WA 字符串和配置原文。
- 发布 JSON 留在项目内可跟踪的 `publish/`；分析中间文件留在被忽略的 `analyze/`。

# Decisions

- 用户已确认：本 change 同时审计修复双平台同类型问题，并把删除命令加入 Skill 和 CLI。
- 用户已确认：删除命令只覆盖插件、配置、WA 主记录；不支持单独删除插件版本文件。
- 用户已再次确认当前完整契约：全量字段审计、双平台六类删除、写前实时读取、写后逐字段读回、仅操作本轮私有测试对象、覆盖五个非探索赛季 build，并按约定保存发布与分析产物。
- 当前事实：NewBee 网页上传接口把插件兼容版本发送为 build 字符串；父分支 `id` 只用于分组/筛选。
- 当前事实：NewBee 主记录删除接口为 `/creator/wow/mod/remove`、`/creator/wow/share_config/delete`、`/creator/wow/wa/delete`；DD 删除能力需以 sidecar/官方接口事实为准。

# Open questions

- 无。当前完整契约已确认。

# Verification expectations

- 运行静态契约审计、Schema/provider/CLI 测试和跨平台回归。
- 对真实只读接口验证动态选项形状；DD 环境若因官方签名/sidecar 启动失败，记录实际失败原因，不伪造通过。
- 对删除命令至少执行 dry-run、缺少确认、目标不存在和成功后 readback 测试；真实删除只对用户明确指定的测试对象执行。
