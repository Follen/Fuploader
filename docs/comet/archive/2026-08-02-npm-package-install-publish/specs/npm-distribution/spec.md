# npm-distribution

## 目标

Fuploader 作为公开 npm 包 `@follenfang/fupload` 分发。npm 全局安装同时提供 `fupload` 命令和版本匹配的 Fuploader Agent Skill；`fupload uninstall` 同时移除这两项由包管理的产物。

首个发布版本为 `0.0.1`，对应 Git tag `v0.0.1`。所有发布版本载体必须严格一致。

## 安装与运行

- 包必须携带 `fupload/SKILL.md`、`agents/`、`references/`、`examples/` 和 `scripts/`。
- `fupload` Node 启动器必须定位包管理的 Skill，发现缺失或版本不匹配时执行受清单约束的原子安装，再调用该 Skill 内的 Python CLI。
- npm 安装环境中的 Skill、README、示例命令和 Agent 工作流必须统一使用 `fupload` 命令，不得要求用户或 Agent 显式定位 Python 文件。
- 仅当维护仓库源码、直接安装 Skill 或 PATH 中不存在 npm CLI 时，文档可以回退到 `python <skill-directory>/scripts/fupload.py`；两种入口必须调用同一 Python 实现并保持相同输出契约。
- 默认 Skill 路径为 `~/.agents/skills/fupload`；调用方可以显式覆盖 Agent home 或 Skill 目录。
- 安装器只替换具有匹配管理记录且文件状态可验证的 Fuploader Skill。未知目录必须报错并保留。
- Python 解释器发现失败时必须返回稳定、可理解的非零错误。

## 升级与卸载

- 包升级必须把包管理的 Skill 更新到与 npm 包相同的版本，并保留未知目录冲突保护。
- `fupload update` 必须从当前全局安装解析 npm prefix，固定安装 `@follenfang/fupload@latest`，然后原子更新默认 Skill 与登记中全部仍有有效管理标记的 Skill。
- 更新不得通过用户输入改变包名或 registry；无有效 Fuploader 管理标记的目录必须保留并在结果中说明。
- 更新结果必须报告更新前后版本、npm 退出状态和各 Skill 状态；npm 或 Skill 同步失败必须返回非零错误并允许重试。
- npm 7 及以上不执行卸载 lifecycle，完整卸载不得依赖 `preuninstall`、`uninstall` 或 `postuninstall`。
- 安装器和启动器必须在用户级登记所有成功采用、安装或升级的默认及自定义 Skill 目标。
- `fupload uninstall` 必须先逐个校验登记路径与目录内管理标记，只删除能够证明由 `@follenfang/fupload` 管理且标记目标与实际路径一致的 Skill。
- 全部受管 Skill 清理成功后，`fupload uninstall` 必须从当前 npm 安装位置解析全局 prefix，并调用 npm 删除 `@follenfang/fupload` 自身，使 CLI shim 和包目录一并删除。
- 任一 Skill 清理失败时不得调用 npm 自卸载，必须保留 CLI 并返回未清理对象，允许用户处理后重试。
- 没有有效管理标记、标记损坏、包名不匹配或目标绑定不一致的目录必须保留并在结果中说明。
- 卸载不得删除用户项目中的发布记录、平台凭据、DD 日志或其他 Skill。
- 直接执行 `npm uninstall -g @follenfang/fupload` 只保证 npm 包和 CLI 被删除，不构成完整卸载；README 与 Skill 必须把 `fupload uninstall` 作为标准卸载命令。

## 包完整性

- 发布包只包含 npm 启动/安装/卸载实现、Fuploader Skill 运行文件和中文 README。
- 发布包不得包含 `analyze/`、`publish/`、测试缓存、字节码、Comet runtime、Git 元数据或任何凭据。
- 生成的 Skill 清单必须记录包版本、Skill 文件路径及内容摘要，安装和卸载均据此验证归属。

## CI 与发布

- GitHub Actions 必须在 Windows 与 Linux 验证 Node 测试、Python 测试、编译、打包清单、全局安装、CLI 启动和完整卸载。
- 版本标签触发发布；Git tag、`package.json`、Skill 分发版本和 workflow 校验版本必须使用同一个标准 SemVer。
- npm 发布使用 Trusted Publishing/OIDC，仓库和 workflow 不持久化 npm token。
- 发布作业必须依赖完整测试作业成功，并以 public access 发布。
