# 插件工作流

## 先调查

1. 读取目标命令 `--help`。
2. 在用户给出的插件目录或当前工作区查找 `.toc`、README、CHANGELOG、发布脚本、已有 ZIP/RAR/7Z、Logo 和截图。
3. 从 `.toc` 提取标题、版本、Interface、作者和说明；从 CHANGELOG/Git 变更整理更新日志。不要覆盖用户明确给出的值。
4. 运行 `newbee option categories` 和 `newbee option game-versions`，按名称展示真实 ID。
5. 编辑或发版前，用 `plugin list` 确认目标，再用 `plugin get` 保存当前详情；需要精确版本文件 ID 时用 `plugin versions list`。

插件发版的 `game_versions` 是 ID 数组，可以同时选择正式服、泰坦重铸、经典旧世等多个目标。

## 上传新插件

需要：名称、1 至 5 个分类、简介、正文及格式、原创属性、Logo、可选截图、首个版本号、游戏版本、插件包和 changelog。

执行：

1. `plugin create`，写后用返回 ID 调 `plugin get`；创建固定为私有。
2. 用户的目标包含首个版本时，使用新 ID 调 `plugin publish-version`，再用 `plugin list` 核对版本。
3. 只有用户明确要求公开时才调 `plugin edit`，随后读回 `public/review_status`。不要为了“完成流程”无条件编辑。

新插件必须先有版本文件才能公开。若在没有版本时调用 `plugin edit`，平台会返回 `code=-4`、`需要上传插件文件后才能公开发布`；不得绕过首版上传或盲目重试公开。

创建成功但发版失败时保留插件 ID，只重试 `publish-version`，不得重新创建同名插件。

## 发布已有插件的新版本

需要：目标插件、版本号、至少一个游戏版本 ID、压缩包、changelog 和频道设置。

1. 读取当前详情和版本摘要，拒绝覆盖同版本。
2. 调 `plugin publish-version`。
3. 用 `plugin list` 验证新版本。若插件已是公开状态，不做多余编辑；若不是公开状态，按既定“更新直接公开”语义调只含 `schema` 和 `id` 的 `plugin edit`，再读回验证。

网络超时后先查版本列表。版本已存在即视为可能已成功，不重复上传。

## 修改插件资料

1. 用 `plugin get` 取得当前详情。
2. 输入只包含 `schema`、`id` 和用户要改变的字段。CLI 会保留其余字段，并设置公开。
3. 需要替换截图时显式提供完整 `screenshots` 列表；`screenshot_files` 会追加到该列表。只增加图片时不要误清空旧图。
4. 调 `plugin edit` 后用 `plugin get` 逐项核对；不上传版本。

可编辑字段：`name`、`categories`、`content_origin`、`content_format`、`intro`、`description`、`logo`/`logo_file`、`screenshots`/`screenshot_files`、`subscribe_plan_level`、`link_to_channel`。

## 修改插件版本日志

1. 用 `plugin changelog list --mod-id <id>` 找到目标版本和 `file_id`。
2. 用 `plugin changelog get --file-id <id>` 读取当前完整日志。
3. 展示版本、旧日志摘要和新日志，确认后调用 `plugin changelog edit`。
4. 再次 `get` 读回验证。该动作不上传版本、不编辑插件资料、不改变公开或审核状态。

输入 schema 为 `fupload.newbee.plugin.changelog.edit.v1`，字段为 `file_id` 和 `changelog`；空日志表示明确清空，不能把缺失字段当作清空。
