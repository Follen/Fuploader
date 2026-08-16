# Outcome

恢复 Fuploader 的 Blackbox provider，使其只使用 Fuploader 托管 Chromium 的网页登录态访问 Workshop API，并实现网页端请求协议。完成 TapTool 的真实读写、压缩包替换与回滚验证后，将 change 合并到 `main`，创建下一版本 tag，并确认 GitHub Actions 发布到 npm。

# Scope

- 解析 Workshop 网页前端的请求参数、认证 Cookie、请求头与 Web `hkey` 签名实现；脱敏分析中间体写入 `analyze/blackbox/client-session-20260816/`。
- 在 Fuploader 管理的 Python venv 中引入 Playwright Chromium。维护 Blackbox 网页会话状态机：先无头探活持久 profile，发现 `login/relogin` 或会话过期时自动弹出有头 Chromium，打开 Workshop 登录入口等待用户完成登录，再回到无头状态复用同一 profile。
- 网页态请求必须通过受控协议实现（Playwright `APIRequestContext`/页面协议桥），使用持久 profile 的 Cookie、网页端字段和网页 signer；不读取 Chrome/Edge/系统浏览器 Cookie 数据库，不接受外部 profile 路径或 Cookie 注入。
- Blackbox 不读取或要求桌面客户端登录态；所有 Workshop API 请求都通过托管 Chromium 的网页会话和网页协议执行。
- 对齐 Workshop 网页端请求签名、时间、nonce、查询字段、Cookie 和必要请求头，不接受用户提供的 Cookie、token、签名或任意 profile 路径。
- 保持插件 list/get/versions、模块元数据 edit、版本 create/edit/delete、ZIP 上传与写后读回能力。
- 使用 `D:\Code\TAP Tool` 和托管 Chromium 网页登录态真实验证目标 TapTool 插件：读取列表/详情/版本，修改并恢复允许的模块字段，创建测试版本、上传 ZIP、替换 ZIP、修改版本字段、删除测试版本，并恢复基线。
- 更新测试、Skill 文档、依赖/版本载体和脱敏验证记录；运行完整 Python、Node、pack、install 与 release 前置检查。
- Verify 通过后归档 change，本地合并到 `main`，从合并后的 `main` 创建并推送下一 SemVer tag，等待 CI 通过并确认 npm `latest` 已更新。

# Non-goals

- 不读取 Chrome/Edge/系统浏览器 Cookie DB；只使用 Fuploader 自己创建并管理的 Chromium persistent profile。
- 不自动代填客户端账号、验证码或二次验证；有头登录窗口由用户完成网页登录。
- 不实现或执行整个插件模块删除。
- 不读取或修改 Heybox 安装目录、桌面客户端配置、客户端二进制或真实凭据。
- 不把 Cookie、token、pkey、设备标识、临时 COS 凭据、完整请求体或原始抓包提交到仓库。
- 不改变 NewBeeBox、DD 或 CurseForge provider 的业务行为。

# Acceptance examples

- 网页 profile 不存在或已过期时，`python fupload/scripts/fupload.py blackbox plugin list` 启动有头 Chromium Workshop 登录窗口；用户完成登录后，网页协议请求返回 `status=ok`，并能读取 TapTool 的详情和版本列表。
- 网页 Cookie 失效时，无头探活转为有头登录；登录完成前不会执行任何写操作，登录完成后继续原始读写操作。
- 桌面客户端未安装、未启动或未登录时不影响 Blackbox；命令不会读取其配置或 Cookie 数据库。
- 对固定 `path/_time/nonce` 回归向量，Python Web signer 与网页前端 signer 输出逐字一致；实际 Workshop 请求不再返回 `relogin`。
- TapTool 的每个允许模块字段在真实 edit 后可读回，并在测试结束前恢复到基线；服务端未立即投影的字段必须记录为已知限制而不是误报成功。
- 测试版本可携带 ZIP 创建；名称、类型、游戏版本和压缩包可替换并读回；删除在必要时只重试一次，最终测试版本不存在或 `auditState=4`。
- 真实测试结束后 TapTool 的模块字段与活动版本集合等于测试前基线，仓库中只保留脱敏证据。
- 归档前所有版本载体已统一到下一 SemVer，manifest、pack、install 与 release 前置检查通过，目标 tag 尚未占用且 tag 发布 workflow 可用；归档后再按固定顺序完成合并、tag CI 与 npm `latest` 核对。

# Constraints and invariants

- 网页通道只使用 Fuploader 管理的 Chromium profile；不读取桌面客户端、Chrome、Edge、Electron 或其他 Playwright profile 的登录态。
- API origin 固定为项目内受支持的 Heybox HTTPS origin，调用方不能覆盖 endpoint、profile 或认证材料。
- Web `hkey` 必须来自可复核的 Workshop 网页前端实现或等价纯 Python 实现，并由至少一个真实成功请求向量与多组差异输入验证。
- 所有输出、异常、日志和分析文件递归脱敏认证、签名、nonce、设备与临时上传凭据。
- 真实写操作串行执行，使用唯一测试标记；不确定 mutation 不自动重放，先只读确认。
- 版本删除最多按既有协议重试一次；不触发整个模块删除。
- 发布顺序固定为 Verify/Archive、合并 `main`、从合并提交创建 tag、推送 tag、等待 CI、查询 npm。

# Decisions

- 用户最新决定不再要求或使用桌面客户端登录态；Blackbox 以 Fuploader 托管 Chromium 的网页登录态作为唯一认证来源。
- 网页登录有效性只以带 Web 协议字段和签名的 `module/list` 成功响应为准，页面 URL 或本地 storage 标记不作为就绪判据。
- 当前主要兼容点是 Workshop 网页端 `hkey` 和 13 个固定查询字段；通过前端 bundle 与真实成功请求建立回归向量。
- 保留现有 Workshop 插件管理操作和 ZIP 上传能力，但任何请求字段以新版客户端和真实成功读回为准。
- 真实测试对象固定为 TapTool，本地插件目录为 `D:\Code\TAP Tool`；测试完成后恢复模块与版本基线。
- 不执行整个插件删除；单个测试版本删除属于验收范围。
- 使用当前独立 Native worktree `comet/use-desktop-client-session`，完成后本地合并至 `main` 并发布下一版本。
- 网页状态机必须区分 `headless_probe`、`headed_login`、`ready`、`expired`、`failed`，并在状态文件中只记录状态、时间和脱敏原因。
- Native Verify 只验收可在归档前完成的产品行为、真实回滚与发布准备；归档、合并、tag CI 和 npm registry 核对是同一用户任务的后续执行步骤，不作为 Verify 通过的前置条件。

# Open questions


# Verification expectations

- 保存客户端版本、关键文件哈希、字节码导出、签名回归向量、会话字段来源与 endpoint/字段矩阵的脱敏分析。
- 单元测试覆盖浏览器 DB 不访问、托管 profile、Web signer 向量、请求字段、错误脱敏和既有 Blackbox 写操作。
- 单元测试覆盖 venv 依赖探测、Playwright profile 状态机、无头到有头转换、登录完成后的状态持久化、网页协议字段和失效重登录；测试使用临时 profile，不接触真实浏览器目录。
- 真实只读验证记录精确命令、退出码和脱敏输出；真实写验证保存 baseline、每步 mutation/readback、最终 rollback 与差异检查。
- 执行 `python -m unittest discover -s fupload/scripts/tests -v`、`python -m compileall -q fupload/scripts`、`npm test`、`npm run check:manifest`、`npm run test:pack`、`npm run test:install` 和版本一致性检查。
- 合并后重新运行发布前检查；推送 tag 后核对 GitHub Actions 状态与 `npm view @follenfang/fupload version`。
