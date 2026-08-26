# Outcome
将 ModUs.Creator 的项目/插件发布能力与 ModUs 主程序的配置分享、WA/字符串能力完整整合到 Fupload。完整不是仅能 CRUD，而是官方客户端暴露的全部可写字段、下拉选项、联动状态和图片入口均完成协议确认、CLI/schema 实现及真实逐字段闭环；完成后重新推送 GitHub并发布高于 `0.0.12` 的 npm 版本。

# Scope
- 复用 `ModUs.Creator` 与 ModUs 主程序各自的本机登录态，不打印认证材料。
- 覆盖 Creator 项目 create/detail/edit/delete、插件版本 list/detail/create/upload/update/edit/delete、真实 ZIP 二进制上传和项目图片字段。
- 覆盖主程序五个 WoW Build 的云备份、配置分享和 WA/字符串的 list/detail/create/update/delete、WA 版本 publish/delete。
- 建立三套完整字段矩阵：Creator 项目/插件、配置分享、WA/字符串。每项记录 CLI 名称、wire 名称、类型、必填、默认值、枚举来源、联动规则、写入接口和回读位置。
- 对每个可编辑字段执行真实“基线回读 -> 单字段修改 -> 提交 -> 回读匹配 -> 恢复 -> 再回读匹配”；数组、下拉、互斥、至少一项、空值和当前账号 tier=无分支均纳入。
- Creator 项目图片覆盖 create 的 logo/screenshot payload 与 edit 的 image upload/delete operations；配置和 WA 覆盖本地图片二进制上传、服务端图片引用提取，以及该引用用于 create/update 后的真实回读。
- 真实测试对象最终按版本、项目/分享顺序清理；ModUs 软删除以 `status=4`、`isPublic=0` 且不出现在活动列表为清理成功。
- 完成全量本地测试、完整真实回归、脱敏证据、GitHub 推送、tag、Trusted Publishing、新 npm registry 版本和真实全局安装。

## Source coverage
- `C:\Users\follen\AppData\Local\Temp\codex-clipboard-a453240e-f371-4076-93c5-7543e71bf9e4.png`：`complete`；发布字符串表单明确包含适用插件、封面&图片、标签、版本号、字符串、同步到大脚、最低订阅等级、正文等字段。保留语义映射到完整目标 Spec 的“WA/字符串字段与图片协议”和 A7、A8、A11；状态 `covered`。
- `D:\Software\Modus`、`C:\Users\follen\AppData\Local\ModUs.Creator\current` 及既有 `analyze/modus*` 静态产物：`complete`（作为协议调查来源）；接口、字段、默认值和枚举必须由 bundle/IL 与真实请求共同确认，映射到完整目标 Spec 全部章节和 A1-A12；状态 `covered`。
- 用户连续修正“全字段回归、完整真实测试”：`complete`；旧结论“媒体上传不在范围”标记为 `superseded`，由本 brief 和 A4-A12 替代。

# Non-goals
- 不改动 NewBee、DD、CurseForge、黑盒或其他平台行为。
- 不用 GUI 或 `computer-use` 操作 ModUs 客户端；协议确认使用静态 bundle/IL、既有本机状态和直接 HTTP/CLI 回归。
- 不在证据中保存 token、cookie、设备标识、签名 URL/query、账号/角色原值、配置正文、WA 代码正文或图片原始内容。
- 只读服务端字段不伪造写能力；必须在字段矩阵标记只读及其回读来源。

# Acceptance examples
- A1：Creator 与主程序两个 `session doctor` 均真实复用对应本机登录态并得到 `api_ready=true`，输出只含脱敏布尔状态。
- A2：Creator 项目字段矩阵完整覆盖名称、别名、摘要、分类、同步、ModUs/大脚至少一项、tier、仓库、依赖、许可证全部子字段、logo/screenshot、图片操作及服务端只读字段；每个可写字段均有真实修改/回读/恢复/再回读记录。
- A3：Creator 项目真实 create/detail/edit/delete；项目 logo/screenshot 创建与图片 upload/delete edit 均提交真实图片内容并回读服务端图片状态。
- A4：Creator 插件版本字段矩阵完整覆盖 project/file ID、version、type、支持游戏版本、MD5、ZIP/解压大小、对象路径、TOC、changelog；create/upload/update/edit/delete 均真实执行，ZIP 原始字节 PUT、写后回读和最终清理成功。
- A5：`modus builds` 返回 Build 0..4；每个 Build 的 backup/config/WA 列表均真实成功，`server` 与 `X-Server-Type` 同步，任何业务 500 必须定位字段并修正，不能当空结果。
- A6：配置分享字段矩阵完整覆盖分页/过滤字段及 `addonsId`、`backupId`、账号/角色、HTML/纯文本正文、`imageUrl`、公开/付费/价格、分享类型、标签、标题、WTF 排除、tier、subType、platform、synchronizationType、Build；每个可写字段真实修改/回读/恢复/再回读。
- A7：配置本地图片通过主程序真实二进制上传取得服务端引用；该引用分别用于配置 create 和 update，detail 回读匹配；随后配置 delete 并验证软删除和活动列表缺失。
- A8：WA/字符串字段矩阵完整覆盖分页/过滤字段及适用插件、封面&图片、标签、版本号、codeText、HTML/纯文本正文、同步到大脚、tier、公开/付费/价格、shareType、subType、platform、synchronizationType、Build；每个可写字段真实修改/回读/恢复/再回读。
- A9：WA 本地图片通过主程序真实二进制上传取得服务端引用；该引用分别用于 WA create 和 update，detail 回读匹配；WA version publish/detail/delete 与 WA delete 均真实完成并最终清理。
- A10：所有下拉/枚举/联动分支有正负向证据，包括分类、游戏版本、适用插件、标签、同步模式、平台至少一项、WTF 与账号/角色、tier=无、付费/价格、Build 0..4；非法组合在远端写入前失败。
- A11：真实证据逐步保存命令、脱敏输入摘要、响应摘要、退出状态，以及正文/图片/ZIP 的长度和 SHA-256；证据能证明写入与回读使用同一内容，又不泄漏原文或签名材料。
- A12：全量 Python/Node、编译、manifest、tarball、隔离安装和脱敏扫描通过；最终代码与文档推送 GitHub，发布高于 `0.0.12` 的新 npm 版本，tag/registry/latest/全局安装版本一致。

# Constraints and invariants
- 写操作只接受版本化 JSON、明确目标 ID 和显式删除确认；每次远端写入后立即回读。
- `platform` 是发布平台字段，不等于 Build；配置/WA 的 Build 同时控制 body `server` 与 `X-Server-Type`。
- 当前账号 tier 列表为空时，真实正确分支是省略 `requiredTierId`；不伪造 tier。
- 图片上传必须使用官方客户端相同的 endpoint、multipart 字段名、必要 headers 和响应字段；HTTP 200 但业务 code 失败不算成功。
- 真实图片、正文和 ZIP 证据只保存长度与 SHA-256，不保存原始内容；签名 URL 必须去 userinfo 和 query。
- `0.0.12` 是遗漏图片上传与全字段闭环的中间版本，不作为本 change 最终验收版本。

# Decisions
- 保持单一 Native change，因为 Creator 项目/版本、配置、WA 的字段矩阵、真实对象清理和最终发布互相依赖。
- 用户要求的是官方客户端全部可用字段和接口，不以“基础 CRUD 已通过”替代逐字段回归。
- 截图中的“封面&图片”是 WA/字符串正式字段；配置界面的同类入口也必须完成本地图片二进制上传，不再仅复用既有云端 URL。
- 不操作桌面客户端；若直接请求失败，继续从 bundle/IL 和 HTTP 请求构造定位 multipart/header/响应契约，直至真实成功或获得明确的协议证据。

# Open questions

# Verification expectations
- Runtime 重跑全量本地检查，独立 Verifier 逐项审 A1-A12。
- 真实矩阵必须是最终代码生成，不复用早于最终字段实现的旧聚合结论；可复用未受代码变化影响的历史步骤，但证据必须标明源码 commit/hash 和复用理由。
- GitHub Actions 的 Windows、Ubuntu、Trusted Publishing 全部成功；npm registry 与真实全局安装回读最终版本。
