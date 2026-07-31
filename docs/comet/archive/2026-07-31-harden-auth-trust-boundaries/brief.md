# Outcome

修复 Fupload 认证和客户端发现的信任边界：环境变量不能再把 NewBee 凭据、Creator 认证头或本地上传内容导向非官方地址；认证目录由 Windows Known Folder 定位；DD 仍能自动发现安装目录，但只执行经过 Authenticode 验证且发布者属于允许集合的官方客户端。doctor 输出脱敏的路径来源、可信 origin、签名和登录状态诊断。

# Scope

- NewBee：固定官方 HTTPS origin；移除生产 API、认证目录、元数据和上传服务器的任意环境覆盖；认证目录使用 Windows Known Folder API；认证请求和带认证上传拒绝跨 origin 重定向。
- DD：使用可信 Windows 用户目录定位 sidecar 状态；保留运行进程、注册表、官方配置和已知根目录发现；对候选 `netease_dd.exe` 执行 Authenticode 验证并校验官方发布者；doctor 返回脱敏发现结果。
- 测试：覆盖恶意环境变量、错误 scheme/host、跨 origin 重定向、认证目录重定向、伪造 DD 可执行文件和现有正常流程。
- 文档：更新 Skill、reference、README、canonical specs 和验证记录，明确环境变量不再是生产覆盖入口。

# Non-goals

- 不改变 create/update/edit 的字段、接口、JSON Schema、发布确认或读回流程。
- 不改变官方 API 的业务 payload、账号状态、DD 原生登录和 WA 原生解析。
- 不提供任意第三方 API、代理或认证目录的运行时切换能力。
- 不把 delete 加入公开 CLI，也不重新创建或修改远端测试对象。

# Acceptance examples

- 默认环境下 `newbee session doctor` 和 `dd session doctor` 仍成功；NewBee 认证与 DD 无头 client 使用官方来源。
- 设置 `FUPLOAD_NEWBEE_API_BASE`、`FUPLOAD_NEWBEE_AUTH_BASE`、`FUPLOAD_NEWBEE_NEXT_API_BASE`、`FUPLOAD_NEWBEE_AUTH_DIR`、`FUPLOAD_NEWBEE_UPLOAD_SERVER` 或 `FUPLOAD_NEWBEE_METADATA_URL` 后，凭据读取和网络动作仍只使用内置可信配置，或在 doctor 前置检查中明确失败；任何 token、device proof、Creator header 和本地上传内容都不发送到该值。
- 非 HTTPS、不同 host、不同 port 或不同 scheme 的认证请求目标被拒绝；官方同源重定向可以继续工作，跨 origin 重定向被拒绝。
- NewBee 凭据只从 Windows Known Folder 下的 `NewBeeBox/auth-store` 读取并写回；环境变量不能将其改到网络共享、项目目录或任意本地目录。
- DD 候选缺失有效 Authenticode 签名、签名链无效或发布者不在允许集合时被拒绝，不启动该 executable。
- doctor 只输出路径来源、规范化 origin、签名状态/发布者、版本和认证布尔状态，不输出 token、cookie、JWT、clientNo、原始 WA 或备份内容。
- `python -m unittest discover -s fupload\\scripts\\tests`、`compileall`、所有示例 dry-run 和现有只读 doctor/build 检查通过。

# Constraints and invariants

- 项目保持纯 Python；只使用标准库和 Windows 系统 API/签名验证能力，不引入 Go、二进制或第三方运行时依赖。
- 任何敏感请求必须在发送前通过固定 origin 检查，并且不能把敏感头或敏感 body 带到跨 origin 重定向。
- DD 官方发布者验证使用稳定的组织身份而非当前单个证书 thumbprint；证书轮换不能破坏正常升级，但未知发布者必须 fail closed。
- 认证目录和 DD sidecar 状态目录创建/写回保持原子行为，不能通过符号链接或重解析点静默改变信任根。
- doctor 失败时先停止认证和 executable 启动，不猜测、不降级到环境变量地址。

# Decisions

- 正常官方生产流程优先于自定义 endpoint、测试 server 和任意认证目录覆盖；测试使用依赖注入或本地 mock。
- DD 安装路径继续自动发现；发现来源可包含运行进程、注册表、官方配置和固定已知根目录，但最终必须做签名和发布者验证。
- 当前环境验证到的 DD 发布者为 `NetEase (Hangzhou) Network Co., Ltd`；实现使用可维护的官方组织允许集合，不锁死当前证书 thumbprint。
- doctor 是只读诊断入口；不为了识别 origin 发起未经固定目标约束的探测请求。
- 用户已确认按本 brief 实施：固定 NewBee 官方 origin 和 Known Folder 认证目录，拒绝环境变量生产覆盖与跨 origin 重定向，DD 自动发现后校验 Authenticode 官方发布者，并保持正常双平台业务行为不变。

# Open questions

- 无

# Verification expectations

- 为每个安全边界增加单元/合同测试，并保留原有 60 项回归覆盖。
- 在当前 Windows 环境运行 NewBee/DD doctor 和只读 build 查询；不执行写入矩阵，避免重新创建已清理对象。
- 检查 git diff、compileall、help/schema、敏感输出脱敏和最终工作区状态。
