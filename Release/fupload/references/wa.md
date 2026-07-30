# WA 工作流

## 先调查

1. 读取目标叶子命令 `--help`，然后用 `wa list` 和 `wa get` 确认目标。
2. 游戏版本用 `option game-versions` 查询；分类用 `wa categories --game-version-id <id>` 查询。
3. 从用户目录、README、CHANGELOG 或已有导出文本整理名称、说明、版本日志和附件。不得在普通输出中展示完整 WA 字符串，只展示长度和 SHA-256 摘要。
4. 附件路径先查 `wa attachment-paths`。共创作者和关联内容必须先 search/list，候选不唯一时让用户按名称和 ID 选择。

## 创建 WA

需要：游戏版本、名称、字符串模式、WA 字符串、首版日志、公开策略，以及按实际使用提供的分类、封面、截图、附件、订阅/价格和频道字段。

1. 生成 `fupload.newbee.wa.create.v1` 输入；单条模式使用 `single`、原始 `wa_str` 和空 `wa_str_titles`。
2. 集合模式使用 `collection`，`wa_str` 是字符串数组的 JSON 文本，`wa_str_titles` 是同序标题数组。
3. 调 `wa create`，随后用返回 ID 调 `wa get`。
4. 用户选择共创、关联内容或分享码时，再依次调用对应 `set` 命令；这些是独立步骤，失败时不得重建 WA。

共创输入 `co_authors` 每项是 `{user_id, share_percent}`，比例使用 0 至 1 的小数且总和不超过 1。关联内容输入 `references` 每项是 `{type, id}`，最多选择网页允许的 4 项。不能只传一组裸 ID。

新建未明确要求公开时保持私有。公开请求可能进入审核，不能报告为审核通过。

## 编辑 WA 元数据

先用 `wa get` 取得当前字段，把保留值和改动值共同整理为 `fupload.newbee.wa.edit.v1`。`wa edit` 只修改名称、说明、媒体、分类、付费、公开和频道等元数据，不修改字符串版本。

编辑已有 WA 按既定策略设置公开。写后用 `wa get` 核对公开/审核状态；需要调整共创、关联内容或分享码时列为后续独立步骤。

## 发布字符串新版本

生成 `fupload.newbee.wa.publish-version.v1`，至少包含 `id`、`wa_str` 和 `wa_log`。version 可以留空，由 CLI 先调用 `get_next_version`；显式版本仍会先读取服务端下一版本，避免脱离远端状态。

调用 `wa publish-version` 后，用 `wa changelog latest` 和 `wa changelog list` 核对版本与日志。网络结果不确定时先读回，不直接重发。

## 修改 WA 版本日志

1. `wa changelog list --id <wa_id>` 找到日志记录 ID。
2. `wa changelog get --id <wa_id>` 读取最新记录，或从列表取得历史摘要。
3. 使用 `fupload.newbee.wa.changelog.edit.v1` 调 `wa changelog edit`，随后重新 list/get。

日志编辑不发布新字符串版本。CLI 不提供 WA、日志、共创或关联内容的删除命令，也不调用任何草稿接口。
