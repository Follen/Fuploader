# Outcome

让 Fuploader 成为可执行的 CurseForge WoW 作者发布工具：能够按作者 ID 查询公开项目、按项目 ID 上传插件 ZIP，并由 npm 安装流程初始化用户主目录下的 CurseForge 配置文件；Skill 在发布编排中主动收集或引导配置所需凭据。

# Scope

- 在 Fupload Skill 中加入 CurseForge 平台选择、凭据准备、项目发现、上传计划、确认、执行和结果验证流程。
- 在 Python CLI 中加入 CurseForge 作者项目查询、游戏版本查询、凭据诊断和插件包上传命令。
- 使用 CurseForge Core API `GET /v1/mods/search?gameId=1&authorId=...` 查询公开项目，并从分页返回值报告总数。
- 使用 CurseForge Upload API `POST https://wow.curseforge.com/api/projects/{projectId}/upload-file` 发送 `multipart/form-data` 的 `metadata` 与 `file`。
- npm 安装、升级和首次 CLI 启动可幂等初始化 `~/.fupload/curseforge.env`，已有文件及真实凭据不得被覆盖。
- 在 `fupload/references/curseforge.md` 详细记录官方 API、认证、字段、状态、限制、示例和 Fuploader 工作流。
- 增加严格 schema、脱敏、平台路由、安装行为、请求构造和失败语义测试；更新 manifest、README 和安装验证。

# Non-goals

- 不通过未公开接口创建、删除或列出作者后台的草稿/待审 Project。
- 不自动创建 CurseForge Project；Project 仍由 Authors 后台创建。
- 不把真实 API Key、Upload Token 或其他凭据写入仓库、发布计划、测试夹具、日志或命令输出。
- 不改变 NewBeeBox 和 DD 的现有协议与行为。

# Acceptance examples

- 给定有效作者 ID 和 Core API Key，`fupload curseforge project list` 返回稳定 JSON，包含公开项目总数以及每个项目的 ID、名称、slug、状态和时间字段。
- 给定有效 Upload Token、已有 projectId、有效 ZIP 与完整 metadata，dry-run 仅校验本地输入；确认后 live 命令上传一次并返回新 file ID，不回显 Token。
- 全新 npm 安装在用户 home 下创建 `~/.fupload/curseforge.env` 模板；重复安装和 `fupload update` 保留用户已经填写的值。
- Skill 在用户要求 CurseForge 上传时，先检查配置；缺少字段则主动询问作者 ID，并要求用户在本机配置 Token/Key 或填写指定 env 文件，不要求把秘密粘贴到对话。
- `fupload/references/curseforge.md` 足以说明 Core API 与 Upload API 是两套认证、作者 ID 的解析方式、上传 metadata 全字段以及公开项目查询的可见性边界。

# Constraints and invariants

- Core API 固定使用官方 HTTPS origin `https://api.curseforge.com` 和 `x-api-key`；WoW Upload API 固定使用 `https://wow.curseforge.com` 和 `X-Api-Token`。
- 配置文件固定在当前用户 home 的 `.fupload/curseforge.env`，不得由项目目录、环境变量或输入 JSON 重定向到任意凭据目录。
- Token/Key 只从进程环境或固定配置文件读取；命令参数和 JSON 输入不接受秘密字段。
- 上传前必须完成 schema 校验、ZIP 文件检查、metadata 构造、dry-run 和一次明确确认；网络结果不确定时不得自动重传。
- npm 安装初始化必须是非破坏、幂等和跨 Windows/POSIX 的；卸载默认保留用户配置与凭据。
- Skill 主文档保持精简，完整 API 字段和示例放入单层 reference。

# Decisions

- change 名为 `curseforge-upload`，使用独立 worktree、分支 `comet/curseforge-upload`，目标分支为 `main`。
- 继续沿用 Fuploader 的版本化 JSON 输入、稳定 JSON 输出、dry-run、写前确认和写后结果核验模型。
- CurseForge 作为第三个平台加入现有 `fupload` CLI 和 Skill，而不是创建独立 Skill。
- Project 创建和私有/待审项目列表保持 Authors Web 后台能力边界。
- `~/.fupload/curseforge.env` 固定保存 `CURSEFORGE_AUTHOR_ID`、`CURSEFORGE_API_KEY` 和 `CURSEFORGE_UPLOAD_TOKEN` 三项；Core 查询与作者上传使用各自独立凭据。
- 进程环境中的同名变量优先于固定配置文件，便于自动化；空值视为缺失，任何来源的秘密均不回显。
- npm 安装和更新仅幂等创建缺失模板，不进行交互式秘密录入，也不覆盖已有文件。

# Open questions

- 无。

# Verification expectations

- 运行 Python 单元测试、Node/npm 测试、manifest 检查、打包检查和全局安装烟测。
- 使用 mock transport 验证 header、URL、query、multipart metadata/file、响应投影、401/403/不确定写入错误和脱敏。
- 在隔离临时 HOME 上验证首次创建、重复安装保留、更新保留、权限与卸载保留配置。
- 运行 Skill Creator `quick_validate.py` 验证修订后的 Skill，并独立前向测试一次 CurseForge 查询与上传编排。
