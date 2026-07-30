---
name: fupload
description: 使用 Fupload CLI 整理并发布魔兽世界作者内容。用户提到 Fupload、新手盒子上传、插件版本日志、创建或更新插件、WA 字符串、修改插件资料、创建或更新配置分享时使用。
---

# Fupload

理解用户目标、从工作区整理资料，再调用 `fupload`。CLI 是唯一写入入口。

## 边界

- 当前只支持平台 `newbee`。`dd` 是预留 ID，不可用。
- 不直接调用新手盒子 HTTP 接口，不读取、保存或索要 token。
- 不使用 Computer Use 操作客户端或网页。CLI 自动复用桌面客户端已有登录态。
- Release 包附带 Windows x64 原生 CLI；使用前要求本机已安装并登录 NewBeeBox 客户端。
- 配置分享只引用用户已经在客户端上传的云备份；不扫描或上传本地 WoW 配置。
- 新建内容未明确要求公开时保持私有。更新已有插件或配置的最终状态为公开，可能重新进入审核。

## 入口

用户已说明动作时直接开始调查。否则只问一次：

```text
你这次要上传新插件、发布插件新版本、修改插件资料或版本日志、创建/更新 WA，还是创建/更新配置分享？
```

按动作只读取一个参考：

- 插件创建、发版或资料编辑：读取 [references/plugin.md](references/plugin.md)。
- WA 创建、编辑、发版、日志或附属关系：读取 [references/wa.md](references/wa.md)。
- 配置创建或更新：读取 [references/config.md](references/config.md)。
- 需要确认命令、输入 schema、输出或失败语义：读取 [references/cli-contract.md](references/cli-contract.md)。

## 找到 CLI

依次使用第一个可用入口：

1. 本 `SKILL.md` 所在 Skill 根目录内的 `bin/fupload.exe`；从 Skill 路径解析，不能按当前工作目录猜测。
2. PATH 中的 `fupload`。
3. Fupload 仓库内的 `bin/fupload.exe`。
4. Fupload 仓库内的 `go run ./cmd/fupload`。

无法确定仓库时不要搜索整台机器，让用户给出 CLI 或仓库路径。每次先读取目标叶子命令的 `--help`；机器调用始终加 `--output json`。

## 执行状态机

1. **调查**：先检查用户给出的目录或当前工作区，再运行只读 CLI。插件资料优先从 `.toc`、README、CHANGELOG、Git 变更、已有压缩包和图片提取；远端 ID、分类、游戏版本、备份和当前详情用 CLI 查询。
2. **补齐**：只询问本地资料和只读查询无法决定的内容。候选不唯一时展示名称与 ID，让用户选择；不让用户手抄可查询 ID。
3. **预检**：生成一个临时 JSON/YAML 输入，检查路径存在；必要时运行同一命令的 `--dry-run --output json`。dry-run 只代表本地输入有效。
4. **确认**：用人话一次展示完整计划，包括目标/ID、原子步骤、主要字段、文件、游戏版本、云备份和公开/审核影响。取得一次确认后不重复询问。
5. **写入**：按计划串行执行。每个命令只做一个业务动作；从 JSON 结果读取新 ID，不解析人类输出。
6. **验证**：每次写入后立即用 list/get/changelog 读回关键字段。空 `data` 不是失败，也不能单独证明落库成功。
7. **报告**：说明成功步骤、远端 ID、公开/审核状态和保留的对象。不得把“已提交审核”说成“审核通过”。

任一步失败立即停止后续写入。报告已成功步骤、可能留下的媒体或对象、失败命令和安全重试入口；网络结果不确定时先只读核对，不能直接重复写入。
