# Outcome

把 Fuploader 发布为公开 npm 包，使用户通过 npm 全局安装后同时获得 `fupload` 命令和可显式调用的 Fuploader Skill；通过单命令 `fupload uninstall` 完整移除该包管理的 Skill 与 npm CLI。

# Scope

- 创建 npm 包清单、Node 启动器、Skill 安装器与单命令自卸载器。
- npm 包携带现有 `fupload/` Skill 及纯 Python CLI，不重写平台业务实现。
- 支持本地 pack、全局安装、命令运行、升级和完整卸载验证。
- 增加 GitHub Actions 跨平台 CI 与基于版本标签的公开 npm 发布工作流。
- 更新中文 README，写明安装、使用、升级、卸载、发布和需要人工完成的 npm 配置。
- 在本机完成不需要额外凭据交互的打包、安装、卸载与发布步骤。

# Non-goals

- 不改变新手盒子、DD 的请求字段、认证或发布业务行为。
- 不删除用户项目中的 `publish/` 记录、平台客户端凭据或 DD 日志。
- 不把 Python 业务实现改写为 JavaScript。

# Acceptance examples

- `npm pack` 产物只包含运行 CLI 和安装 Skill 所需文件，不包含 `analyze/`、凭据、测试缓存或 Comet 运行状态。
- 全局安装 tarball 后，`fupload --help` 调用包内 Python CLI，默认 Skill 安装到用户 Agent Skill 目录。
- 升级同一 npm 包时，包管理的 Skill 原子更新到匹配版本。
- `fupload update` 把 npm CLI 更新到 `@follenfang/fupload@latest`，并把默认及全部登记有效的 Skill 同步到相同版本。
- `fupload uninstall` 成功后，`fupload` 命令、npm 包与该包管理的全部 Skill 目录都不存在；用户项目发布记录和平台数据保留。
- 某个受管 Skill 无法删除时，`fupload uninstall` 返回稳定错误且不调用 npm 删除自身，CLI 保持可用以便修复后重试。
- GitHub Actions 在 Windows 和 Linux 运行 Node、Python、pack、安装及卸载测试；版本标签通过 npm Trusted Publishing 发布公开包。

# Constraints and invariants

- Node.js 最低版本与 GitHub Actions、npm Trusted Publishing 兼容。
- Python CLI 路径从已安装 Skill 目录解析，不依赖当前工作目录。
- 安装与升级不能覆盖无法证明由 Fuploader npm 包管理的未知目录。
- 卸载只清理由本 npm 包创建并记录的 Skill，不扫描或删除其他 Skill。
- npm 包、测试输出、日志和 Actions 不包含 token、cookie、签名 URL 或平台凭据。
- npm 安装生命周期脚本失败必须给出可执行错误，不能伪装成完整安装。
- npm 7 及以上不执行卸载 lifecycle；不得依赖 `preuninstall`、`uninstall` 或 `postuninstall` 实现完整卸载。

# Decisions

- npm 包名为 `@follenfang/fupload`。
- npm 可执行命令名为 `fupload`。
- npm 安装后的 Skill 和文档统一把 `fupload` 作为执行入口，不再显式拼接 Python 路径；源码维护或 PATH 中没有 npm CLI 时才保留 Python 回退。
- 首个发布版本为 `0.0.1`，Git tag 为 `v0.0.1`。
- Skill 版本、`package.json` 版本、Git tag 和发布 workflow 校验版本必须完全一致。
- 用户已确认按本 brief 与 `npm-distribution` 完整规格直接进入实现。
- 默认 Skill 目标遵循当前 Agent 约定：`~/.agents/skills/fupload`，并允许显式目录覆盖。
- npm 包使用公开访问级别；发布 CI 使用 GitHub Actions OIDC / npm Trusted Publishing，不在仓库保存 npm token。
- 卸载不清理用户项目的 `publish/`、客户端认证目录或平台数据。
- 用户指定的参考任务已经验证 npm 7+ 的卸载 lifecycle 不执行；完整卸载采用 `fupload uninstall`：先清理受管 Skill，再从当前安装 prefix 调用 npm 全局卸载 `@follenfang/fupload`。
- 用户明确要求提供 `fupload update`，作为 npm CLI 与全部受管 Skill 的统一升级入口。
- 安装器登记默认、Agent home 覆盖和 `--skill-dir` 产生的全部受管 Skill 目标；卸载逐一交叉验证登记与目录内管理标记后删除，未知目录保留。
- Skill 清理失败时停止，不调用 npm 自卸载；清理成功后 npm 自卸载失败时保留明确错误，命令仍可重试 npm 删除步骤。

# Open questions

无。

# Verification expectations

- 现有 Python 单元测试与 compileall 全部通过。
- Node 单元测试覆盖路径解析、清单校验、Skill 安装/升级/冲突保护和卸载。
- 在隔离 HOME/npm prefix 中验证 tarball 的全局安装、CLI 调用、升级与 `fupload uninstall` 完整自卸载。
- `npm pack --dry-run`/包清单审计确认敏感和无关文件未进入包。
- GitHub Actions YAML 可解析，发布版本、Git tag 与 Skill/包版本保持一致。
