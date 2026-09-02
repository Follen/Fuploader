# Outcome

Fuploader 的 DD provider 自动复用当前 Windows 官方 DD 客户端持久化的邮箱或手机号登录态。`dd session start` 根据官方账号与凭据枚举选择正确的原生重登录流；登录成功后的 JWT、作者 API、动态读取、上传、写入、读回和清理继续共用同一套 task session 与业务实现。

# Scope

- 从官方 `AccountCredStorage` 读取 auto account 与 credential，只按 `Account.method`、`Cred.type` 和 `Cred.modifier` 做严格分流。
- `urs + urs_token + normal` 使用 `UrsReLoginFlow(controller, sdk, token, username)`，支持邮箱登录态复用。
- `mobile + urs_mobile_token + mobile_password|mobile_uplink` 使用现有 `MobileReLoginFlow`，保持手机号密码与上行登录态复用。
- 不通过先调用一种流、失败后再尝试另一种流来猜测凭据类型；未知或互相矛盾的枚举组合在原生登录前失败。
- 两类登录态共用现有单 broker、单 sidecar、单次登录、串行请求、显式 logout、十分钟异常兜底和登录后的全部 DD 资源代码。
- 补齐分流、错误、进程生命周期和敏感信息脱敏的自动化测试与用户文档。
- 使用当前受信官方 DD 客户端，分别在邮箱和手机登录态下完成全部非探索赛季 build 的插件、配置和 WA 真实 create/update/edit/delete、读回与依赖顺序清理。

# Non-goals

- 不接收用户手工输入的邮箱、手机号、密码、token、Cookie、JWT 或 `clientNo`。
- 不新增二维码、第三方 OAuth、Cookie-only 或其他未明确支持的持久化登录态。
- 不复制或分叉登录成功后的 DD 发布实现。
- 不改变非 Windows 平台不支持 DD provider 的边界。
- 不改变插件、配置、WA 已确认的字段、wire、上传、读回和删除语义。

# Acceptance examples

- A1：官方客户端当前持久化 `Account.method=urs`、`Cred.type=urs_token`、`Cred.modifier=normal` 时，`dd session start` 自动使用 `UrsReLoginFlow`，邮箱登录完成后 JWT 和作者 API ready；不要求用户提供凭据。
- A2：官方客户端当前持久化 `Account.method=mobile`、`Cred.type=urs_mobile_token` 且 modifier 为 `mobile_password` 或 `mobile_uplink` 时，`dd session start` 自动使用 `MobileReLoginFlow` 并保持现有手机登录行为。
- A3：缺失、未知或相互矛盾的账号/凭据枚举组合在调用任何原生登录流前确定性失败；错误只暴露安全枚举与阶段，不泄漏账号名、凭据、token、Cookie、JWT 或 `clientNo`，也不自动尝试另一条登录流。
- A4：两类登录态都只启动一个 broker、一个 sidecar 和一次匹配的原生重登录；登录后复用同一 JWT、作者 API client、GET、上传、mutation、读回和 logout 管线，失败与超时均无遗留进程或 broker state。
- A5：DD 会话分流矩阵、broker 生命周期、脱敏、完整 Python 测试、编译、manifest、tarball 和隔离安装检查全部通过，且现有手机登录相关合同无回归。
- A6：邮箱登录态下，当前全部非探索赛季 build 的依赖读取成功，插件、配置、WA 的真实 create/update/edit/delete、上传、读回和最终清理全部成功并生成脱敏证据。
- A7：手机登录态下执行与 A6 相同的全量真实矩阵并成功；证据分别记录所用安全 credential kind、实际命令、退出状态、读回与清理结果，不记录敏感凭据。
- A8：DD Skill/reference 和完整 `dd-publishing` Spec 明确说明自动邮箱/手机分流、支持矩阵、失败语义、共用登录后代码和两类登录态的真实验证要求。

# Constraints and invariants

- 只执行通过现有 Authenticode 与安装结构校验的官方 `netease_dd.exe` 和其版本匹配的 `ccvoicehub.res`。
- `dd session doctor` 保持只读，不创建登录会话；关闭官方 GUI 仍需用户明确同意。
- credential kind 可以作为安全枚举用于诊断与证据，账号名和 credential value 永不进入 CLI、日志或分析证据。
- 写入不确定性、GET-first 恢复、签名 URL、二进制上传、资源所有权与删除顺序沿用现有 DD 合同。
- 真实测试只清理本轮记录的隔离测试对象，不操作其他远端对象。

# Decisions

- 使用官方枚举做显式 dispatch，而不是根据账号字符串形态判断邮箱或手机号。
- 邮箱使用 `UrsReLoginFlow`；手机继续使用 `MobileReLoginFlow`，并从 modifier 计算 `isPassword`。
- 登录成功后只保留一个公共 session tuple 和公共资源执行路径，不增加 email/mobile 业务分支。
- 对邮箱和手机登录态分别执行全量真实资源矩阵，而不是用单元测试或单一登录 smoke 替代。
- 本 change 使用独立 worktree；完成并验收后合并到 `main` 并删除 worktree。

# Open questions

- 无。

# Verification expectations

- 自动化检查至少包括 DD session focused tests、全量 Python suite、`compileall`、Node suite、manifest/version、pack 和隔离安装门禁。
- 真实检查分别在邮箱与手机持久化登录态下执行 `session doctor/start/status/stop`、JWT/作者 API ready、全部非探索赛季 build 的读取矩阵，以及插件/配置/WA create/update/edit/delete、二进制上传、写后读回和依赖顺序清理。
- 两轮真实证据必须绑定最终实现 commit 和当前 DD 版本/资源哈希，输出只含安全枚举、摘要、长度、SHA-256、业务码与对象测试标识。
- 验证结束必须确认无 `netease_dd.exe` sidecar、无 broker 进程、无 live broker state，且所有测试对象均已清理或明确列出需人工处理的阻塞项。
