# Outcome

Fupload 在用户显式选择新手盒子插件、字符串或配置分享工作流后，优先识别并使用官方
Creator Center CLI（`ncc`），不再默认把自研 Python provider 作为首选写入通道。Skill
携带一份来自官方机器可读端点的完整 CLI 文档引用，使 Agent 能按当前命令契约规划、执行和
解释结果，同时以不进入对话、仓库或命令参数的方式接收凭据。

# Scope

- 更新 `fupload/SKILL.md` 的新手盒子路由、探测、凭据、执行、确认与错误处理流程。
- 将 `https://creator.newbeebox.com/md/cli-docs` 的完整 UTF-8 Markdown 内容纳入
  `fupload/references/`，并在 Skill 中按需引用。
- 覆盖官方 CLI 当前支持的插件、WA/字符串、配置分享查询、创建、资料编辑、内容推送、同步、
  打包、云备份、评论和媒体命令；以 `ncc docs`、`--help` 和 `-o json` 为运行时契约。
- 给出适合 Agent 的令牌交付方案：优先复用已登录的官方 CLI；自动化时读取调用进程已有的
  `NCC_TOKEN`；缺少认证时指导用户在自己的终端完成登录或环境注入。
- 保留现有 Python CLI，但仅在用户显式要求使用第三方 Python 管理工具时选择该通道。

# Non-goals

- 不把用户令牌、CLI 登录配置或官方文档抓取中间文件提交到 Git。
- 不逆向、复制或修改官方 npm 包实现，不新增自研 HTTP 调用来模拟 `ncc`。
- 不扩展 DD 的路由或字段契约。
- 不在本 change 中发布、修改或删除用户的正式线上内容。
- 不承诺官方 CLI 文档未声明支持的多字符串/附件更新、配置版本更新或主记录删除能力。

# Acceptance examples

- 用户显式调用 Fupload 并要求更新新手盒子插件时，Agent 先检测是否已安装 `ncc`；已安装
  即默认选择官方通道，除非用户显式要求第三方 Python 管理工具。执行前运行 `ncc docs` 和
  目标叶子 `--help`，再用 `-o json` 执行。
- 用户机器未安装 `ncc` 时，Agent 询问是否改用官方 CLI；用户同意后检查 Node.js >= 18、
  安装官方 npm 包、验证版本/help，并说明如何创建令牌和建立本机登录态。
- 用户已通过官方 CLI 登录时，Agent 通过 `ncc whoami -o json` 验证身份，不索要令牌。
- 自动化环境已有 `NCC_TOKEN` 时，Agent 让子进程继承该变量，不把值拼入命令、JSON、
  `publish/`、日志或答复。
- 用户直接把令牌发进对话时，Agent不复述、不写盘，提示吊销该令牌并采用本机登录或
  `NCC_TOKEN` 创建替代凭据。
- 官方 CLI 不支持目标动作时，Agent 说明能力缺口；只有用户随后显式要求第三方 Python 管理
  工具，才切换通道并重新调查、规划和确认，不得静默回退或伪造 `ncc` 命令。
- Skill 引用文件完整包含抓取时官方 `/md/cli-docs` 的正文，并标注来源 URL、获取日期与
  运行时优先读取 `ncc docs` 的规则。

# Constraints and invariants

- Fupload 仍只由用户显式调用。
- 官方 CLI 安装包固定使用 `@newbeebox/newbeebox-creator-center-cli@latest`；运行前检查
  Node.js >= 18、`ncc -V`、`ncc --help`、`ncc docs` 与 `ncc whoami -o json`。
- 所有 Agent 调用使用非交互模式和 `-o json`；写入前保留现有调查、完整计划、dry-run（命令
  支持时）和用户确认约束，写入后用官方 info/list/versions 等只读命令核对。
- 凭据不得进入聊天复述、Skill、reference、代码、Git、`publish/`、`analyze/`、命令参数、
  命令历史、错误摘要或测试夹具。不得把真实令牌传给 `ncc login --token ...` 的 Agent 命令。
- 本轮用户在对话中提供的令牌只视为待吊销凭据，不用于实现、测试或持久化。
- 官方 CLI 文档是能力边界；文档声明只能网页端或桌面客户端完成的动作不能改写成 CLI 支持。
- 探索赛季继续排除在真实变更测试之外。

# Decisions

- 使用官方公开机器可读端点 `/md/cli-docs`，而不是从压缩后的网页 bundle 人工重建文档。
- 完整官方文档作为 Skill 内引用快照；每次执行仍先读取本机已安装版本的 `ncc docs`，避免
  静态快照覆盖运行时版本契约。
- 推荐凭据顺序：已登录的官方 CLI > 调用环境预置 `NCC_TOKEN` > 用户在自己的终端完成
  `ncc login`；Agent 不收集或保存明文令牌。
- 用户已在本轮提供的明文令牌不进入任何工具调用或项目文件。
- 路由顺序由用户确认：先检测 `ncc`；已安装默认官方；未安装先询问是否采用官方，确认后
  代为安装并指导建立登录态；只有用户显式要求第三方 Python 管理工具时才使用现有 CLI。
- 官方能力不足不触发自动 fallback。Agent 说明缺口后等待用户显式选择第三方工具；切换前
  重新读取远端状态并重新确认计划。
- 用户已确认本 brief 与 `newbee-official-cli` 完整目标规格，可进入 Build。

# Open questions

无。

# Verification expectations

- 对比官方 `/md/cli-docs`、项目内引用文件和 `ncc docs` 的命令章节与安全规则。
- 在无 `NCC_TOKEN` 的干净环境验证探测不会输出或索要明文令牌。
- 安装官方 CLI 后验证版本、help、docs、未登录 whoami 的退出码与 JSON 错误结构。
- 用 mock/subprocess 单元测试覆盖 CLI 可用、缺失、未登录、不支持动作和 JSON 错误分支；敏感
  扫描确认无 `ncc_` 令牌值进入 tracked 文件。
- 运行现有 Python 单元测试、`compileall`、Skill 文本检查与 `git diff --check`，确认 DD 和
  Python fallback 未发生意外回归。
