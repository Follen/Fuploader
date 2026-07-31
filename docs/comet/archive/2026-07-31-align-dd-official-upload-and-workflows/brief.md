# Outcome

让 Fupload 的 DD 插件、配置与 WA 发布链路按官方客户端协议工作，并消除批量任务中反复启动原生登录会话造成的账号“顶号”风险。上传授权、对象 PUT、业务写入和读回必须分别报告真实阶段与结果；明确的 HTTP/业务拒绝不能再伪装成 `verification_required`。

# Scope

- 全量审计 DD 官方客户端与当前实现的登录、JWT、作者 API、动态 GET、三类资源上传、create/update/edit/delete、读回、错误和清理链路。
- 插件包上传授权固定使用官方传输名 `addon.zip`、`file_type=a19-ui-res`、`business_id=addon`、`mime_type=application/x-zip-compressed`；本地 ZIP 名称、插件显示名称和 ZIP 内部目录保持不变。
- 审计并对齐插件图片、配置图片、WA 图片和 WA 材质包的官方授权字段、MIME、对象 PUT header、大小限制和业务名；不得把本地展示文件名直接当作签名对象名。
- 将 DD 错误分为 `upload_authorize`、`object_put`、业务 mutation 和 `readback` 阶段，保留 HTTP 状态、业务码和脱敏 endpoint。只有传输结果不确定或写成功后的读回不确定才设置 `verification_required`。
- 修复 DD 会话生命周期：Skill 检测到官方 GUI 后，先明确告知用户将关闭 DD 并取得一次同意；CLI 只关闭已验证的官方 GUI 进程并确认其完全退出，随后同一发布任务的 doctor、动态读取、写入和读回应复用一个原生登录会话。无同意、关闭失败或进程身份不确定时不触发 `MobileReLoginFlow`；并发调用只能排队使用同一会话。
- 对所有文件输入做端到端协议审计，不限于已复现的插件 ZIP：插件包、插件 logo/详情图、配置展示图、WA 展示图和 WA 材质包均覆盖本地路径解析、扩展名/MIME、授权 query、固定/省略 wire 文件名、signed URL 保真、对象 PUT header/body、业务 payload、读回和错误阶段。测试名覆盖空格、中文、括号、`+`、`#`、`%` 与 Unicode。
- 更新 Python CLI、Fupload Skill、DD reference、help/schema 和回归测试，使 Agent 默认使用新的会话与错误恢复契约。
- 把 DD 网页表单的联动控件改写为显式只读依赖图：Agent 必须先选择父项并执行对应 GET，展示当前父项下的子候选，直到依赖闭合后才生成一次最终写入 JSON；Python 在执行写入前通过同一原生会话重复这些 GET 并验证父子归属。
- 使用当前登录 DD 环境做真实插件、配置、WA 和所有支持 build 的验证；探索赛季保持用户既定非目标。

# Non-goals

- 不修改或注入 DD 桌面客户端，不读取 GUI 进程内存或 Cookie，不调用仅供 DD 服务端下发的 remote command 通道，不修改凭据库、账号凭据或 ZIP 内插件目录。
- 不复刻 DD 登录、NEP 签名或对象存储签名算法；继续调用已验证官方安装中的原生模块。
- 不把一个 HTTP 403 归因为账号顶号，也不通过改插件显示名、改 ZIP 内容或生成新 `clientNo` 绕过协议错误。
- 不并行提交 DD 写操作，不自动重发结果不确定的写入，不恢复探索赛季验证。
- 不改变 NewBeeBox 的上传、认证和会话行为，除共享错误模型必须保持兼容外不触碰其业务实现。

# Acceptance examples

- 同一份 `OmniCC v11.2.8 Rurutia fix.zip` 直接作为本地输入时，授权请求使用固定 `addon.zip`，对象 PUT 和 `/addon/create|modify` 成功；远端插件名称仍来自表单 `name`，ZIP 内容哈希不变。
- 本地 ZIP 名含空格、中文、括号、`+`、`#` 或 Unicode 时，插件与 WA 上传授权均不受本地 basename 影响；官方固定传输名和 MIME 与参考客户端一致。
- 对象 PUT 返回明确 HTTP 403 时，输出阶段为 `object_put`、保留 `http_status=403`、`verification_required=false`，并且不调用业务 mutation。
- `/addon/modify` 已接受但读回暂不可见时，输出 mutation 已接受、阶段为 `readback` 且 `verification_required=true`；调用方先 GET，不自动重发。
- GUI DD 正在运行时，`session doctor` 只完成安装/签名/冲突诊断，不登录；Skill 展示将关闭的官方 DD 实例并询问一次。用户不同意时 sidecar 进程数、登录次数和写入次数都保持为零。
- 用户同意后，CLI 先请求 GUI 正常退出，限时后终止仍存活且身份再次校验通过的官方 GUI 进程；全部退出才启动 headless。身份不一致、出现新 GUI 进程或关闭失败时停止。
- 一次包含 doctor、options、六个串行插件 create 及逐项读回的任务只执行一次原生 relogin；不存在六个并发 sidecar，第一项失败后后五项不执行。任务结束后 headless 退出。
- 两个同时发起的 DD CLI 操作由同一受控 headless 会话串行处理或明确返回忙碌状态，不启动第二个登录流。
- 会话异常退出后，已开始的写入按不确定结果处理并先读回；未开始的步骤保持未执行，重新建立会话不会盲目重放。
- 插件、配置、WA 的图片和资源上传各有官方协议合同测试；真实验证报告记录每个阶段、字面 HTTP/业务结果、登录次数、进程数和读回结论，但不记录 token、JWT、Cookie、clientNo 或 signed URL。
- 配置创建时，Agent 先列出云备份并取得 `backup_sn`，再读取备份详情；选定 WTF 账号/服务器/角色后才展示该账号下可选的 known/unknown WA。最终 JSON 只含 `backup_sn`、WTF selector 和 WA 稳定引用，不含复制的备份对象。
- 若用户在最终确认前更换 `backup_sn`、WTF 账号、房间、插件主分类或游戏类型，Agent 清空并重新 GET 所有下游选择；若这些关系在最终 JSON 生成后或执行前发生漂移，Python 在任何上传或 mutation 前以精确字段路径拒绝。

# Constraints and invariants

- 继续使用稳定独立且不输出的 Fupload DD `clientNo`；不得读取、打印或轮换现有值来处理本问题。
- 只启动通过 Authenticode 与官方发布者校验的 DD executable；状态目录继续来自 Windows Known Folder。
- 一个 Windows 用户同一时刻最多一个 Fupload DD 原生会话；官方 GUI 与 Fupload headless 会话不得同时登录，所有网络命令在 headless 会话内严格串行。
- 上传授权名是 wire 常量，不改变本地文件、插件显示名或压缩包内部结构。
- signed URL 必须作为不透明值原样交给对象 PUT，不能因空格、`+`、`#`、`%`、Unicode 或重复编码而解析、拼接、解码或重编码；本地 basename 不能泄漏到官方规定固定或省略的 `file_name`。
- 写操作遇到明确 4xx/5xx 或业务非零码时视为确定失败；超时、连接中断等无法确认服务端是否处理的情况才要求读回验证。
- 真实测试仅使用明确标识的测试对象；测试对象清理由验证报告限定 SN，不能扩大到既有对象。
- 动态子项只在其父项上下文中有效。最终 JSON 必须同时携带父字段与稳定子 ID/opaque selector；显示名称仅用于交互，不参与 wire payload。GET 返回的完整 backend 对象、时间戳和签名 URL 不得复制进写入 JSON。
- `analyze/` 继续被忽略，只保存官方拆包、探针和探索报告；正式行为、Skill 与 CLI 文档必须位于受跟踪项目范围。

# Decisions

- 2026-07-31：插件包官方 wire 文件名固定为 `addon.zip`；显示名仍由 `/addon/create|modify` 的 `name` 字段决定。
- 2026-07-31：当前 403 的已复现实因是原始 basename 进入签名授权；相同字节改用安全传输名即成功，与账号、ClientNo 和插件显示名无关。
- 2026-07-31：截图确认朋友的 GUI 实际收到服务端“下线通知 / 异常顶号退出”；不是 403 的展示误判。
- 2026-07-31：静态探针确认 Fupload 持久化 `clientNo` 与 GUI 不同，官方生成器每次生成不同值；顶号不是误用了 GUI 的同一设备标识。
- 2026-07-31：`MobileReLoginFlow` 会调用 `LoginController.startLogin` 并发送完整 CC 握手；GUI 的 `LoginController._onKickOutPush` 收到服务端 push 后先 logout，再原样显示 reason。朋友侧顶号由第二个完整账号会话触发，连续 CLI relogin 会重复放大该问题。
- 2026-07-31：无 GUI Cookie 的 `UiApiClient.login()` 实测返回业务码 411，不能只靠 NEP 签名取得作者账号态；官方 `WowExecutor` 可复用 GUI Cookie，但命令入口是服务端 CID23 下发而非本机 IPC，不能供 Fupload 稳定调用。
- 2026-07-31：现有文件锁只阻止 Fupload sidecar 并发，既不阻止第一次 sidecar 顶掉 GUI，也不阻止一批独立 CLI 依次重复登录。
- 2026-07-31：用户确认采用 GUI 关闭保护：Skill 必须先询问并取得同意，再由 CLI 关闭官方 DD GUI；随后整次任务只登录一次，成功或失败后退出，10 分钟空闲超时仅作为异常兜底。
- 2026-07-31：未经同意不得关闭 GUI；CLI 不能通过普通资源命令隐式启动 headless，会话必须经显式 start 建立并经 stop/finally 收口。
- 2026-07-31：空格文件问题扩展为所有 DD 文件输入的全链路审计；每种资源分别以官方证据确定 `file_name` 是固定值、空值还是省略，不从相邻资源类推。
- 2026-07-31：三类资源、所有上传类型、读写 endpoint 和错误分类都纳入本 change，全量对齐而非只修插件 ZIP 一个字段。
- 2026-07-31：探索赛季不做真实写入验证。
- 2026-07-31：CLI+JSON 与 GUI 联动控件的差异采用“两阶段选择、一次 JSON、写前复验”：Agent 先按依赖图逐层 GET 并展示候选，依赖闭合后生成最终 JSON；Python 在同一 task session 内重复 live GET，校验每个子 ID/selector 仍属于 JSON 中的父项，然后从最新 GET 重建官方完整对象。任何上游变化都会使下游选择失效，不填猜测默认值。
- 2026-07-31：官方已有 SN 后锁住的是外层免费/付费使用方式；`need_buy`、`need_anchor_vip` 是付费方式子项，已有付费对象仍可按官方页面调整子项及价格/有效期/VIP。CLI 从 GET 派生 outer mode 并禁止直接跨模式，不把两个 wire 字段整体误标成 create-only。

# Open questions

- 无。

# Verification expectations

- 静态对照官方 pyc/cache、旧 known-good probe 与当前 provider，形成 endpoint、方法、字段、固定传输名、MIME、header、响应和错误语义矩阵。
- 单元与合同测试覆盖三类资源全部上传、特殊本地文件名、各阶段 4xx/5xx/业务错误/超时、确定失败与不确定结果边界、敏感信息脱敏和读回恢复。
- 进程级测试用可计数 fake native runtime 验证 GUI 冲突时零 relogin、一次任务一次 relogin、并发串行、失败即停、空闲退出和崩溃恢复。
- 当前登录 GUI 上先做只读 doctor 和未确认 start 拒绝测试，证明零 sidecar、零 relogin、GUI 不下线；真实关闭 GUI 测试必须再次取得用户确认。随后执行完整真实写入矩阵，验证结束后 headless 会话必须退出，用户可重新打开 GUI。
- 文件链路矩阵对每种本地文件输入至少覆盖普通 ASCII 名、空格名、中文名和保留字符名；逐阶段断言 wire `file_name`、MIME、business、signed URL、PUT header、状态码、mutation 是否发生及读回结果。
- 当前登录 DD 环境真实执行插件、配置、WA 的 create/update/edit/delete 与读回，覆盖动态返回的全部非探索赛季 build；批量六插件场景使用新会话模型重跑并记录实际原生登录次数。
- 对原始问题 ZIP 做回归：记录原始 SHA-256、授权元数据、对象 PUT 状态和后续业务结果；不改变原包。
- 运行完整 Python 测试、CLI help/schema/reference 完整性审计和敏感输出扫描；最终报告明确列出仍受官方服务状态限制的检查。

# Shape confirmation

- 2026-07-31：用户明确确认上述完整目标、范围、关键决定、验收标准和非目标，可进入 Build。
