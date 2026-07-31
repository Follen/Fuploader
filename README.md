# Fuploader

Fuploader 是一个面向 Agent 的《魔兽世界》作者发布 Skill，使用纯 Python CLI 操作新手盒子（NewBeeBox）和网易 DD 的插件、配置分享与 WA/字符串。

项目强调显式调用、完整字段收集、写入前确认和写入后读回验证。CLI 只负责单次原子读写，业务选择、执行计划和异常恢复由 Agent 在对话中完成。

## 功能

- 支持新手盒子和网易 DD 双平台。
- 支持插件、配置分享、WA/字符串的创建、内容更新与元数据编辑。
- 覆盖平台页面可设置字段，包括版本、游戏分支、分类、媒体、可见性、审核、商业设置、频道、关联内容和配置备份选择。
- 编辑和更新采用 `GET -> 动态选项查询 -> presence-aware patch -> 写入 -> 读回` 流程；省略字段表示保留已有值。
- 写入输入使用严格 JSON Schema：未知字段、重复键、`NaN` 和 `Infinity` 均会被拒绝。
- 凭据取自桌面客户端登录状态，不接收或输出 token、cookie、JWT、签名 URL、DD `clientNo`、原始 WA 字符串或原始配置内容。
- DD 通过已安装官方客户端的无头运行环境完成原生登录、签名和 WA 解析。

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

- Windows
- Python 3
- 已安装并登录新手盒子桌面客户端（使用新手盒子时）
- 已安装并登录网易 DD 官方客户端（使用 DD 时）

新手盒子认证读取 `%APPDATA%/NewBeeBox/auth-store`。DD 会自动查找安装目录，并把稳定的 sidecar 设备状态保存在 `%APPDATA%/CCVoiceHub/Fupload/sidecar-device.json`。

## 作为 Skill 使用

将仓库中的 `fupload/` 目录安装到 Agent 的 Skill 目录，并显式调用：

```text
$fupload
```

该 Skill 不会因普通提及“发布”“新手盒子”或“DD”而自动触发。Agent 会先询问平台、资源和动作，读取所需契约与动态选项，然后在被发布项目中创建 `publish/<时间>-<平台>-<资源>-<动作>/`。同一次发布的 JSON 按原子步骤保存为 `01-<动作>.json`、`02-<动作>.json`，执行完成后保留为项目发布记录。Agent 会先对这些文件执行 dry-run；只有在展示完整写入计划并得到确认后才会执行真实写入。

## CLI 使用

查看总帮助：

```powershell
python fupload\scripts\fupload.py --help
```

查看具体操作的可执行字段契约：

```powershell
python fupload\scripts\fupload.py newbee plugin create --help
python fupload\scripts\fupload.py dd config update --help
```

检查桌面登录状态：

```powershell
python fupload\scripts\fupload.py newbee session doctor
python fupload\scripts\fupload.py dd session doctor
```

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
2. 使用只读命令获取账号记录、分类、版本、备份、频道和关联候选，不猜测 ID。
3. 配置分享必须选择对应桌面客户端已经上传的云端备份。
4. 每次独立发布都在目标项目的 `publish/` 下创建新目录，不把 JSON 写入 Skill 目录，也不自动删除发布记录。
5. 先执行 `--dry-run`，再向用户展示所有修改、保留和清空字段。
6. 得到明确确认后串行写入，每步成功后立即读回验证。
7. 遇到 `verification_required` 时先读取远端状态，再决定是否重试。

完整契约见：

- [工作流与 CLI 契约](fupload/references/workflow.md)
- [新手盒子字段参考](fupload/references/newbee.md)
- [网易 DD 字段参考](fupload/references/dd.md)

## 测试

```powershell
python -m unittest discover -s fupload\scripts\tests
python -m compileall -q fupload\scripts
```

当前回归测试覆盖 CLI 路由、严格 JSON、字段 Schema、双平台 builder、动态选项校验、字段保留与清空语义，以及所有内置示例的 dry-run。

## 说明

Fuploader 依赖第三方桌面客户端和线上接口的当前行为。客户端版本或接口发生变化后，应先运行 session doctor 和只读命令，并重新验证字段契约。该项目不是新手盒子或网易 DD 的官方项目。
