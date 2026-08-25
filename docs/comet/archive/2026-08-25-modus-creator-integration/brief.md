# Outcome

将 ModUs.Creator 的插件作者能力整合进 Fupload：复用本机登录态，覆盖项目/插件发布的读取、创建、修改、删除、版本管理、签名 ZIP 二进制上传和发布后校验，并保留 JSON CLI/Skill 的现有平台契约。

# Scope

- 新增 `modus` 平台 provider、schema、CLI 命令树和文档入口。
- 复用 `C:\Users\follen\AppData\Local\ModUs.Creator\auth\token.dat`，使用 Windows DPAPI CurrentUser 和熵 `ModUs.Creator.TokenStore.v1` 解密，所有 API 请求使用 Bearer。
- 覆盖插件相关接口：作者项目列表/详情/创建/修改/删除；发布文件列表/详情；文件 ID 分配；发布元数据创建/修改；签名 URL 获取；ZIP 二进制上传；发布文件删除；游戏版本/分类等动态读取接口。
- 完整覆盖 Creator 项目表单状态机和项目字段：选择游戏、基本信息、许可证三个步骤；发布平台至少选择一个，ModUs 与大脚 BigFoot 可同时选择；当前账号的订阅等级下拉本来就是“无”，服务端返回空枚举并以 `requiredTierId=null` 提交；分类为下拉/枚举；许可证包含模板、版权所有者、年份和正文；每个字段必须记录 API wire 名称、JSON 类型、必填/可选、枚举来源、联动/互斥规则和回读位置。
- 上传链必须完成“登记元数据 -> 获取签名 URL -> 上传 ZIP 字节 -> 读取详情/列表校验”的完整闭环，不能只提交本地 ZIP 路径。
- 增加脱敏诊断、schema 校验、单元/黑盒测试和 ModUs 真实端到端测试记录；完成最早 change 中的真实全量矩阵后，才允许 GitHub 推送和 NPM 发包并结束本 change。

# Non-goals

- 不修改 `ModUs.Creator` 安装目录。
- 不接入 ModUs 的备份、字体、材质、订阅、钱包或非插件内容能力。
- 不把 token、cookie、签名 URL 或 ZIP 内容写入日志、测试报告或提交物。

# Acceptance examples

- A1：同一 Windows 用户存在 Creator `token.dat` 时，Fupload `modus session doctor` 能报告 token 存在、DPAPI 可解密和 API 就绪状态，但不输出 token。
- A2：`modus project list/get` 能读取作者项目；`modus project create/edit/delete` 能完成项目生命周期并校验返回对象。
- A3：`modus plugin list/get/versions` 能读取插件和版本；动态游戏版本、分类和发布字段可读取。
- A4：`modus plugin create/upload` 对 ZIP 计算 MD5、ZIP 大小、解压大小及 TOC 字段，完成文件 ID、元数据、签名 URL、二进制上传和远端回读。
- A5：`modus plugin update/edit/delete` 能分别修改发布内容/元数据并删除指定发布或项目，删除后回读确认状态。
- A6：所有写操作要求版本化 JSON、正 ID 和显式目标；dry-run 不发送远端请求；错误输出脱敏且包含阶段/端点。
- A7：完成一次真实 ModUs 测试矩阵：登录态读取、项目读取、插件读取、创建、上传、详情回读、版本更新、元数据修改、发布删除和测试项目清理；每项保存命令、脱敏输入、字面响应摘要和退出状态。
- A8：项目创建/编辑状态机按“选择游戏 -> 基本信息 -> 许可证”推进；未完成前置步骤时 CLI/schema 拒绝提交，并能保留当前状态。
- A9：发布平台字段要求至少一个选项；ModUs 与 BigFoot 可同时选择；ModUs-only、BigFoot-only 和双平台组合均有真实请求/回读证据。
- A10：订阅等级使用服务端下拉枚举；当前账号的真实枚举为空，Creator 只展示“无”，项目以 `requiredTierId=null` 提交并回读；BigFoot 组合也强制为 null，不构造不存在的付费等级或收益分支。
- A11：许可证模板、版权所有者、版权年份和许可证正文均映射到真实 wire 字段；模板切换和正文修改可单字段回归并恢复原值。
- A12：分类下拉、图片/截图、名称、别名、摘要、同步类型、仓库地址、依赖和服务端返回的所有项目字段均记录 JSON 类型、可选性、枚举来源和回读字段；未知字段保持阻塞而不猜测。
- A13：项目每个可编辑字段完成“修改 -> 真实回读 -> 恢复 -> 再回读”，并保存脱敏命令、字面响应摘要和退出码。
- A14：项目字段的空值、默认值、非法值、正整数 ID、至少一项平台和状态机越级提交均有真实或明确服务端错误回归。
- A15：最早 change 的真实全量矩阵全部完成：登录态、项目 list/detail/create/update/delete、发布 file list/detail/fileId、元数据 create/update/delete、签名 URL、ZIP PUT、发布和项目清理回读。
- A16：真实测试专用项目和最小合法 ZIP 在任一阶段失败时保留事务记录，不假报成功；清理按发布文件后项目顺序执行并回读确认不存在。
- A17：完整本地测试、ModUs 专项测试、CLI/schema 测试、打包检查和安装检查全部通过，结果记录在验收证据中。
- A18：项目字段契约、状态机、真实回归矩阵和发布报告写入脱敏文档，不包含 token、cookie、密文、签名 URL 或 ZIP 内容。
- A19：所有变更提交到 Git，推送到 GitHub `origin` 目标分支成功，并记录最终提交哈希和远端状态。
- A20：`@follenfang/fupload` 版本、manifest、tarball 内容一致，`npm publish --access public` 成功，registry 回读该版本成功；A19 与 A20 均完成才允许 Archive。

# Constraints and invariants

- API 基址为 `https://app.modus.cool/api/`，默认对象键模板为 `modus/wow/addons/{projectId}/files/{fileId}.zip`。
- 认证只使用本机 DPAPI token；Cookie 不作为主认证依赖。
- signed URL 由服务端返回，客户端不自行拼接对象存储上传地址。
- 修改/删除必须使用明确的 project/file ID，并在写后执行回读。
- 真实测试优先使用专用测试项目和最小 ZIP；任何远端写操作前保留完整操作记录，报告只存脱敏值。

# Decisions

- 采用单一 Native change，不拆分 child；平台 provider、schema、CLI、测试和文档共享同一接口契约，拆分会增加协调成本。
- 平台名称采用 `modus`，与现有 `newbee`、`dd`、`curseforge`、`blackbox` 并列。
- 复用 Creator DPAPI token，不复制或迁移 Creator WebView2 profile。
- 真实测试采用专用临时 ModUs 项目：自动创建测试项目和最小测试插件，覆盖创建/上传/更新/修改/删除，结束时删除测试发布和测试项目并回读确认。

# Open questions

- Q1 已解决：使用自动创建并清理的专用 ModUs 测试项目。
- Q2 已解决：发布平台不是互斥选择；ModUs 和大脚可同时选，但至少保留一个平台。
- Q3 已解决：当前账号的付费 tier 本来就是“无”；`tiers=[]` 与 `requiredTierId=null` 是正确业务状态，不创建临时订阅等级。

# Verification expectations

- 开发期：现有 Python 测试套件、ModUs provider/schema 单测、CLI dry-run/错误脱敏测试。
- 验收期：由独立只读 Verifier 按 A1-A20 执行，真实端到端记录不得包含敏感认证材料；所有真实写入、回读、恢复和清理必须先完成，GitHub 推送与 NPM 发包作为最后两个门禁。

## Source coverage

- `codex-clipboard-a0ad0c07-5e0e-4c0e-8d66-f7dc8ad6af62.png`（创建项目选择游戏页）：`complete`；步骤导航“选择游戏/基本信息/许可证”；对应 Spec“项目状态机”；对应验收 A8/A9；`covered`。
- `codex-clipboard-24ef6f64-5600-4d3d-b2ca-7fe2378e6525.png`、`codex-clipboard-187f01e9-6271-4e82-a489-d5853b75c9cb.png`、`codex-clipboard-8581139c-e3f7-4140-8ba7-b964998fe18b.png`（平台和订阅选择）：`complete`；至少选择一个平台，ModUs/BigFoot 可共选，订阅等级下拉影响收益说明；对应 Spec“平台与订阅状态机”；对应验收 A9/A10；`covered`。
- `codex-clipboard-78380c28-a056-48b0-82fd-7731891e53e0.png`（许可证页）：`complete`；模板、版权所有者、年份、正文；对应 Spec“许可证字段”；对应验收 A11/A12；`covered`。
- `codex-clipboard-d4aba703-1fb8-4301-bbca-b47c0a512415.png`（分类下拉）：`complete`；分类为枚举下拉；对应 Spec“项目字段 wire 契约”；对应验收 A8/A12；`covered`。
