# Outcome

恢复 Fuploader 的 Blackbox provider，使其使用本机 Heybox 1.14.1 客户端登录态访问 Workshop API，并保留插件列表、详情、版本管理、压缩包上传和版本删除重试能力；完成脱敏协议分析、真实 TapTool 验证、合并、tag 和 npm 发布。

# Scope

- 读取 `%APPDATA%/heybox-pc-launcher/config.json` 的新版客户端 session，解密并组合请求所需的账号、pkey、token 和客户端身份参数。
- 保留旧 Chromium Cookie DB 作为兼容回退，但新版 config session 优先。
- 对齐新版客户端请求签名、客户端版本字段、设备身份和认证头。
- 更新 Blackbox COS 上传链路，兼容新版 `api.xiaoheihe.cn/bbs/app/api/qcloud/cos/upload/*/v2` 协议，并保留旧 Workshop 上传回退。
- 将网页版登录后的静态/动态接口分析写入 `analyze/`，仅保留脱敏路径、字段、状态、哈希和证据摘要。
- 真实测试 plugin list/detail/versions、模块元数据回读、版本创建/编辑、压缩包替换、删除及删除重试；不执行整个插件删除。
- 运行项目测试、构建和 npm 发布流程，合并 worktree 到 `main` 并创建版本 tag。

# Non-goals

- 不自动完成网页登录、验证码或账号登录流程。
- 不实现整个插件模块删除。
- 不把 Cookie、token、pkey、签名、设备标识或原始抓包写入仓库/分析产物。
- 不改动与 Blackbox 链路无关的 provider 或发布元数据。

# Acceptance examples

- 在存在新版本机客户端登录态时，`python fupload/scripts/fupload.py blackbox plugin list` 返回 `status=ok`，并可读取目标插件详情与版本列表。
- 版本创建包含名称、类型、游戏版本和压缩包 URL；版本列表回读这些字段且压缩包 URL 非空。
- 版本名称、类型、游戏版本和压缩包 URL 可逐项更新并回读匹配；删除在必要时重试后 `auditState=4`。
- 真实测试结束后目标插件模块字段和活动版本集合与基线一致。
- 生产测试、npm 打包、tag 和 npm 发布均有可复核命令及结果记录。

# Constraints and invariants

- API 请求继续使用 `status=ok` 作为成功判定，失败必须保留 endpoint 和验证上下文。
- 新版客户端默认身份为 `x_client_type=pc`、`x_os_type=Windows`、`x_app=heybox_pc`、资源版本 `1.14.1`；签名时间偏移按客户端实现对齐。
- 所有写操作在真实测试中使用可回滚标记和独立版本，最终不得留下活动测试版本。
- 分析中间体存放在被 `.gitignore` 忽略的 `analyze/`，并通过脱敏脚本生成。

# Decisions

- 采用客户端 `config.json` session 优先、旧 `Network/Cookies` 回退的认证加载策略。
- 继续使用旧 `workshopapi.xiaoheihe.cn/wow/open_platform/module*` 管理接口；仅替换已确认失配的新版 COS 上传协议。
- 版本删除保留一次延迟回读和必要的第二次删除重试；不增加整个模块删除操作。
- 在独立 Native worktree 中实现，Verify 通过后合并到 `main`，再按项目当前 npm 版本策略发布。

# Open questions

# Verification expectations

- 静态检查新版 `app.asar`、Workshop bundle 和网页版捕获，形成脱敏路由/字段报告。
- 单元测试覆盖 config 解密、session 选择、时间偏移签名和新旧 COS body 映射。
- 使用本机客户端登录态执行真实只读与写入测试，保存 baseline、modified、verification 和 rollback 证据。
- 执行完整 Python 测试、npm pack/publish 前置检查、版本 tag 检查和发布后 npm 版本查询。
