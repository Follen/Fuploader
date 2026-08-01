# Fuploader

Fuploader 是一个面向 Agent 的《魔兽世界》作者发布 Skill。新手盒子（NewBeeBox）默认优先使用官方 `ncc` CLI；用户显式要求第三方管理工具时可使用项目内纯 Python CLI。网易 DD 使用项目内 Python CLI 调用官方无头客户端。

项目强调显式调用、完整字段收集、写入前确认和写入后读回验证。CLI 只负责单次原子读写，业务选择、执行计划和异常恢复由 Agent 在对话中完成。

## 功能

- 支持新手盒子官方 `ncc`、第三方 Python 管理通道和网易 DD。
- 支持插件、配置分享、WA/字符串的创建、内容更新与元数据编辑。
- 官方通道严格采用已安装 `ncc` 暴露的能力；第三方 Python 通道覆盖版本、游戏分支、分类、媒体、可见性、审核、商业设置、频道、关联内容和配置备份选择等页面字段。
- 第三方 Python 以 Creator Center 网页的请求和表单状态为基准，编辑和更新采用 `GET -> 动态选项查询 -> presence-aware patch -> 写入 -> 读回`；关联作者/内容在主记录读回后替换并再次读回。官方通道采用 `ncc` 文档规定的只读查询、写入和读回命令。
- 第三方 Python 写入使用严格 JSON Schema：未知字段、重复键、`NaN` 和 `Infinity` 均会被拒绝；官方 `ncc` 使用参数和 `-o json` 结构化输出。
- 新手盒子官方通道复用本机 `ncc login` 或预先注入的 `NCC_TOKEN`，第三方通道复用桌面客户端登录状态；不接收或输出 token、cookie、JWT、签名 URL、DD `clientNo`、原始 WA 字符串或原始配置内容。
- DD 通过已安装官方客户端的无头运行环境完成原生登录、签名和官方 `WowUIInterface.parseWa` WA2 解析；一次发布任务只建立一个串行会话，任务结束立即退出。
- DD 写入前按官方网页的详情投影和表单校验重建完整请求；可选 VIP/频道依赖只在启用时查询，插件版本历史遍历分页，WA 新版本只接受纯数字。4xx/业务错误会在 DD 版本目录的 `Fupload/logs` 保存经过递归脱敏且按 UTF-8 字节限长的请求与响应记录。

## 目录

```text
fupload/
|- SKILL.md                 # Agent Skill 主入口
|- agents/openai.yaml       # Skill 元数据
|- references/              # 工作流和双平台完整字段契约
|- examples/                # 双平台 JSON 输入示例
`- scripts/
   |- fupload.py            # CLI 入口
   |- fupload_cli/          # Python 实现
   `- tests/                # 回归测试
```

`analyze/` 用于本地探索、真实验证中间文件和报告，已被 Git 忽略。

## 环境要求

- 新手盒子官方通道：Windows、macOS 或 Linux，Node.js >= 18、官方 `ncc` CLI 与本机登录态
- 新手盒子第三方 Python 通道：Windows、Python 3、已安装并登录新手盒子桌面客户端
- 网易 DD：Windows、Python 3、已安装并登录官方客户端

官方 `ncc` 的安装命令为 `npm i -g @newbeebox/newbeebox-creator-center-cli@latest`。Fuploader 不读取其凭据文件；用户在自己的终端完成 `ncc login`，Agent 仅用 `ncc whoami -o json` 验证。自动化可在启动 Agent 前注入 `NCC_TOKEN`，令牌不得写入命令参数、项目文件或 Git。

第三方 Python 通道的认证目录由 Windows Known Folder API 定位到用户 Roaming AppData 下的 `NewBeeBox/auth-store`。NewBee API、认证、元数据和上传 origin 固定为官方 HTTPS 地址，环境变量不能重定向凭据或文件。DD 会自动查找安装目录，验证 `netease_dd.exe` 的 Authenticode 官方发布者后再启动，并把稳定的 sidecar 设备状态保存在 Roaming AppData 下的 `CCVoiceHub/Fupload/sidecar-device.json`。

## 作为 Skill 使用

将仓库中的 `fupload/` 目录安装到 Agent 的 Skill 目录，并显式调用：

```text
$fupload
```

该 Skill 不会因普通提及“发布”“新手盒子”或“DD”而自动触发。Agent 会先询问平台、资源和动作。新手盒子会自动检测 `ncc`：已安装即默认使用官方通道；未安装时先询问是否安装；只有用户显式选择第三方 Python 管理工具才进入项目内 CLI。Agent 在被发布项目中创建 `publish/<时间>-<平台>-<资源>-<动作>/`，同一次发布的脱敏 JSON 按原子步骤保存为 `01-<动作>.json`、`02-<动作>.json`。展示完整写入计划并得到确认后才会真实写入。

## CLI 使用

新手盒子官方 CLI：

```powershell
npm i -g @newbeebox/newbeebox-creator-center-cli@latest
ncc -V
ncc docs
ncc whoami -o json
```

创建令牌和本机登录说明见[官方 CLI 文档](https://creator.newbeebox.com/cli-docs)。不要把令牌粘贴到 Agent 对话；在自己的终端完成 `ncc login`。

以下为项目内第三方 Python CLI 与 DD 执行层。

查看总帮助：

```powershell
python fupload\scripts\fupload.py --help
```

查看具体操作的可执行字段契约：

```powershell
python fupload\scripts\fupload.py newbee plugin create --help
python fupload\scripts\fupload.py dd config update --help
```

检查桌面登录与安装状态：

```powershell
python fupload\scripts\fupload.py newbee session doctor
python fupload\scripts\fupload.py dd session doctor
```

DD doctor 不会登录。若输出 `gui_running=true`，需先取得用户同意，随后关闭已验证的官方 GUI 并建立一个任务会话：

```powershell
python fupload\scripts\fupload.py dd session start --confirm-close-gui
python fupload\scripts\fupload.py dd options game-types --session <session-id>
python fupload\scripts\fupload.py dd session stop --session <session-id>
```

GUI 未运行时，`session start` 不加 `--confirm-close-gui`。后续 DD 的动态查询、写入和读回都传同一个 `--session`，并在 `finally` 中 stop。

读取当前游戏分支：

```powershell
python fupload\scripts\fupload.py newbee plugin game-versions
python fupload\scripts\fupload.py dd options game-types
```

写操作只接受 JSON 输入。建议先 dry-run：

```powershell
python fupload\scripts\fupload.py newbee plugin create --input fupload\examples\newbee-plugin-create.json --dry-run
python fupload\scripts\fupload.py dd plugin update --input fupload\examples\dd-plugin-update.json --dry-run
```

所有命令输出一个 `schema=fupload.output.v1` 的 JSON 对象。退出码 `0` 表示成功，退出码 `2` 表示校验、会话、平台或写后验证错误。

## 工作流约束

1. 写入前先运行目标 leaf command 的 `--help`，以运行时 Schema 为准。
2. 使用只读命令获取账号记录、分类、版本、备份、频道和关联候选，不猜测 ID；DD 的全部命令复用一个任务 session。
3. DD 配置按 `backup_sn -> backup detail -> WTF 账号/服务器/角色 -> 该账号的 WA` 逐层选择，依赖闭合后只生成一次最终 JSON。
4. 每次独立发布都在目标项目的 `publish/` 下创建新目录，不把 JSON 写入 Skill 目录，也不自动删除发布记录。
5. 第三方 Python 写入先执行 `--dry-run`；官方 `ncc` 只对文档声明支持的叶子执行 dry-run，例如 `addons push --dry-run`。
6. 得到明确确认后串行写入，每步成功后立即读回验证。
7. 遇到 `verification_required` 时先读取远端状态，再决定是否重试。

完整契约见：

- [工作流与 CLI 契约](fupload/references/workflow.md)
- [新手盒子官方 CLI 完整参考](fupload/references/newbee-official-cli.md)
- [新手盒子第三方 Python 字段参考](fupload/references/newbee.md)
- [网易 DD 字段参考](fupload/references/dd.md)

## 测试

```powershell
python -m unittest discover -s fupload\scripts\tests
python -m compileall -q fupload\scripts
```

当前回归测试覆盖 CLI 路由、严格 JSON、字段 Schema、双平台 builder、动态选项校验、字段保留与清空语义，以及所有内置示例的 dry-run。

## 说明

官方 `ncc` 通道以已安装版本的 `ncc docs` 和叶子 `--help` 为执行契约；仓库内官方文档是获取时的完整快照。第三方 Python 与 DD 通道依赖桌面客户端和线上接口的当前行为，客户端版本或接口变化后应先运行 session doctor 和只读命令。Fuploader 项目本身不是新手盒子或网易 DD 的官方项目。
