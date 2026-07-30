# Fupload

Fupload 是面向 Agent 的魔兽世界内容发布工具。`Fupload` Skill 负责询问、整理和确认，Go/Cobra CLI 负责执行单个原子业务动作。

首版只支持新手盒子。平台位于一级命令：

```text
fupload newbee ...
```

未来网易 DD 使用预留的平台 ID `dd`，即 `fupload dd ...`，但当前没有不可用的伪实现。

## 构建

需要 Go 1.26 或兼容版本：

```powershell
go build -o bin/fupload.exe ./cmd/fupload
```

CLI 自动复用 `%APPDATA%\NewBeeBox\auth-store` 中的桌面客户端登录态。请先登录 NewBeeBox 客户端；不要向 Agent 提供 token。

## 命令树

```text
fupload newbee plugin list
fupload newbee plugin get
fupload newbee plugin create
fupload newbee plugin edit
fupload newbee plugin publish-version
fupload newbee plugin versions list
fupload newbee plugin changelog list|get|edit
fupload newbee wa list|get|categories|attachment-paths
fupload newbee wa create|edit|publish-version
fupload newbee wa media upload
fupload newbee wa changelog latest|get|list|edit
fupload newbee wa co-author search|list|set
fupload newbee wa reference search|list|set
fupload newbee wa share-code set
fupload newbee backup list
fupload newbee backup get
fupload newbee config list
fupload newbee config get
fupload newbee config create
fupload newbee config update
fupload newbee option categories
fupload newbee option game-versions
```

每一级命令都提供详细帮助：

```powershell
fupload --help
fupload newbee plugin --help
fupload newbee plugin publish-version --help
```

## 输入和输出

所有写命令使用版本化的结构化输入：

```powershell
fupload newbee plugin create --input examples/newbee/plugin-create.yaml
Get-Content release.json | fupload newbee plugin publish-version --input - --output json
```

文件支持 `.yaml`、`.yml` 和 `.json`。`--input -` 只接收一个 JSON 文档。未知字段、缺少必填字段和非法本地文件会在联网前失败。

写命令收到合法输入后直接执行。预检使用：

```powershell
fupload newbee config create --input config.yaml --dry-run --output json
```

`--dry-run` 只证明本地 schema 和文件校验通过，不证明远端权限、分类 ID 或游戏版本 ID 有效。

## 原子语义

- `plugin create`：只创建私有插件元数据。
- `plugin edit`：合并远端详情、编辑元数据并设置公开，可能进入审核。
- `plugin publish-version`：只上传一个新版本，同版本已存在时拒绝覆盖。
- `plugin changelog edit`：只修改一个已有版本文件的日志。
- `wa create`：创建 WA 元数据和首个字符串版本。
- `wa edit`：只编辑已有 WA 元数据并设置公开。
- `wa publish-version`：先取得下一版本号，再发布字符串和版本日志。
- WA 的日志、共创作者、关联内容、分享码与媒体均为独立原子命令。
- `config create`：引用客户端已有 `cloud_id` 创建配置分享。
- `config update`：合并远端详情并固定设置公开，可能进入审核。
- `backup get`/`config get`：只返回发布所需的安全字段，不输出角色 ZIP、哈希或原始 WTF。

“上传新插件”是 Skill 工作流，不是复合 CLI 命令。Skill 一次确认后执行 `plugin create` 和 `plugin publish-version`；只有用户明确要求公开时才执行 `plugin edit`。任何一步失败都会停止并报告已经创建的远端 ID。

新手盒子不允许没有版本文件的插件公开。新建并公开时必须先成功执行 `plugin publish-version`，再执行 `plugin edit`；顺序错误会返回 `code=-4`。

## 配置分享

Fupload 不上传 WoW 云端备份。先在 NewBeeBox 客户端上传配置，然后查询：

```powershell
fupload newbee backup list --output json
fupload newbee backup get --cloud-id 3571309 --output json
```

选择返回的 `cloud_id`，再填写 `config-create` 或 `config-update` 输入。更换配置更新的 `cloud_id` 时，必须重新提供 `linked_mods`、三个 `ignored_*` 列表和 `role_id`。

插件分类和游戏版本从平台公开元数据查询，不要硬编码。插件版本的 `game_versions` 可以选择多个；配置的游戏版本由所选云备份决定。

## Schema 示例

完整示例位于 [examples/newbee](examples/newbee)：

- `plugin-create.yaml`
- `plugin-edit.yaml`
- `plugin-version.yaml`
- `config-create.yaml`
- `config-update.yaml`
- `plugin-changelog-edit.yaml`
- `wa-create.yaml`
- `wa-edit.yaml`
- `wa-version.yaml`
- `wa-changelog-edit.yaml`

## 安全和错误恢复

- 普通输出不会打印 access token、author token、resource token 或一次性登录 code。
- API 成功必须同时满足 HTTP 2xx 和业务 `code == 1`。
- 网络结果不确定时先运行只读命令核对远端状态，不盲目重复写入。
- “设置公开”可能只是提交审核；CLI 不会把审核中报告为审核通过。
- 当前不提供删除、草稿、攻略、本地配置打包或网易 DD 写入。

## 分发 Skill

可直接分发的 Codex Skill 位于 `Release/fupload`。将整个 `fupload` 目录复制到接收者的 `$CODEX_HOME/skills`（未设置时为 `~/.codex/skills`）并重新加载 Codex；包内 `bin/fupload.exe` 是 Windows x64 原生 CLI，接收者需要已安装并登录 NewBeeBox 客户端。
