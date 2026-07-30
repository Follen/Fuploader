# CLI 契约

## 只读命令

```text
fupload newbee plugin list|get
fupload newbee plugin versions list
fupload newbee plugin changelog list|get
fupload newbee backup list|get
fupload newbee config list|get
fupload newbee option categories|game-versions
fupload newbee wa list|get|categories|attachment-paths
fupload newbee wa changelog latest|get|list
fupload newbee wa co-author search|list
fupload newbee wa reference search|list
```

`backup get` 和 `config get` 已过滤 ZIP、哈希、原始 WTF 与凭据。不得绕过它们读取原始接口。

## 写命令

```text
fupload newbee plugin create --input <path|->
fupload newbee plugin edit --input <path|->
fupload newbee plugin publish-version --input <path|->
fupload newbee plugin changelog edit --input <path|->
fupload newbee config create --input <path|->
fupload newbee config update --input <path|->
fupload newbee wa create|edit|publish-version --input <path|->
fupload newbee wa media upload --input <path|->
fupload newbee wa changelog edit --input <path|->
fupload newbee wa co-author set --input <path|->
fupload newbee wa reference set --input <path|->
fupload newbee wa share-code set --input <path|->
```

输入支持 JSON/YAML 文件；`--input -` 只接收 JSON。写命令收到合法输入就执行，`--dry-run` 只做本地校验。每个 schema 和字段以目标命令当前 `--help` 为准。

## Schema

| 动作 | schema |
| --- | --- |
| 插件创建 | `fupload.newbee.plugin-create.v1` |
| 插件编辑 | `fupload.newbee.plugin-edit.v1` |
| 插件版本 | `fupload.newbee.plugin-version.v1` |
| 插件版本日志编辑 | `fupload.newbee.plugin.changelog.edit.v1` |
| 配置创建 | `fupload.newbee.config-create.v1` |
| 配置更新 | `fupload.newbee.config-update.v1` |
| WA 创建 | `fupload.newbee.wa.create.v1` |
| WA 元数据编辑 | `fupload.newbee.wa.edit.v1` |
| WA 字符串新版本 | `fupload.newbee.wa.publish-version.v1` |
| WA 媒体上传 | `fupload.newbee.wa.media.upload.v1` |
| WA 日志编辑 | `fupload.newbee.wa.changelog.edit.v1` |
| WA 联合作者设置 | `fupload.newbee.wa.co-author.set.v1` |
| WA 关联内容设置 | `fupload.newbee.wa.reference.set.v1` |
| WA 分享码设置 | `fupload.newbee.wa.share-code.set.v1` |

WA `attachments` 是 `{name,install_type,install_path,value,is_compressed,timestamp?}` 对象数组；共创 `co_authors` 是 `{user_id,share_percent}` 数组；关联 `references` 是 `{type,id}` 数组。不得把这些字段简化成裸 ID 数组。

## JSON 输出

所有机器调用加 `--output json`。成功顶层包含 `schema/platform/operation/success/data`；dry-run 还含 `dry_run=true`。错误输出含结构化 `error.message` 并返回非零退出码。

不要假定成功 `data` 一定有 ID：插件发版/编辑、WA 写入和配置更新可能返回空对象或数组。每次写后用 list/get 验证；WA 版本与日志再用 changelog 命令核对。失败时保留原始退出码和脱敏消息，不打印 token、完整 WA 字符串或 URL 查询参数。

## 平台

当前只调用 `fupload newbee ...`。`fupload dd ...` 会稳定返回未支持错误；不得回退或伪装为新手盒子。
