# Outcome
将 ModUs 主程序的配置分享与字符串/WA 管理能力完整整合到 Fupload，复用本机登录态并支持多个 WoW Build；真实完成读写回归后推送 GitHub 并发布新的 npm 包。

# Scope
- 从 `D:\Software\Modus`、主程序 bundle、运行态存储和本机登录态确认接口、字段、方法、默认值、枚举、Build 映射和状态联动。
- Fupload 实现 ModUs 主程序 session 复用、Build 列表/选择、配置备份与配置分享接口、字符串/WA 接口及版本接口。
- 配置和 WA 的 list/detail/create/update/delete 必须使用真实账号执行；每次写入后回读，测试对象最终清理。
- 覆盖 `retail=0`、`classic_era=1`、`classic=2`、`classic_titan=3`、`anniversary=4` 等客户端 Build ID；接口请求体 `server` 与 `X-Server-Type` 必须同步。
- 完成 Python/Node 测试、逐 Build 真实回归、GitHub 推送和新 npm 版本发布。

# Non-goals
- 不改动 NewBee、DD、CurseForge 或其他无关平台行为。
- 不输出 token、cookie、设备标识、签名 URL、配置正文或字符串正文。

# Acceptance examples
- A1：`modus session doctor` 从本机 ModUs 登录态得到 `api_ready=true`，输出无认证材料。
- A2：`modus builds` 返回所有已确认 Build 的 id/code/name，当前 Build 可被显式选择。
- A3：每个 Build 的配置备份列表、配置分享列表和 WA 列表真实请求成功；业务 500 时记录实际字段/Build 并修正后重试，不能把 500 当空列表。
- A4：配置分享真实 create、detail、update、delete，所有写后回读成功，最终对象不存在。
- A5：WA/字符串真实 create、detail、update、version publish（若账号允许）、delete，所有写后回读成功，最终对象不存在。
- A6：请求字段与主程序 bundle 一致，包含分页、server、platform、mine、status、shareType、orderBy、同步、公开/付费、tier、内容和 Build 联动字段。
- A7：全量本地测试、编译和脱敏扫描通过；真实回归证据保存命令、输入摘要、响应摘要和退出状态。
- A8：代码、文档和测试推送到 GitHub；新 npm 包 manifest/tarball/registry 版本一致并可全局安装。

# Constraints and invariants
- 写操作只接受版本化 JSON、正整数 ID 和显式删除确认；写后必须回读。
- `platform` 是发布平台字段，不等于 Build；配置/WA 多平台字段按服务端约束处理。
- 当前账号付费 tier 为空时使用 `requiredTierId=null` 的真实分支，不伪造 tier。
- 真实测试对象必须按发布/分享后项目顺序清理，cleanup 最终为空。

# Decisions
- 使用单一 Native change：配置、WA、Build 和发布共享同一 ModUs 客户端与字段契约，分拆会产生文件和真实对象协调冲突。
- 以主程序 bundle 的固定 Build 映射和本机当前状态为协议来源；默认请求不再硬编码错误 Build。
- 先修正字段/Build 后再判断业务结果，服务端 500 作为可诊断错误保留。

# Open questions

# Verification expectations
- 运行 ModUs 专项与全量 Python/Node 测试、compileall、diff 检查。
- 使用当前本机登录态对每个 Build 做只读列表/详情回归，并对可安全创建的测试对象执行配置与 WA CRUD、回读和删除。
- 保存脱敏真实回归 JSON；核对 GitHub HEAD/远端、npm manifest/tarball/registry 与全局安装。
