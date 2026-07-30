# 配置分享工作流

## 前置条件

先告诉用户：配置必须已在 NewBeeBox 客户端上传为云端备份。不要打包本地 WoW 目录。

1. 运行 `backup list`，展示备份名称、`cloud_id`、游戏版本、时间和数量摘要。
2. 用户选择后运行 `backup get --cloud-id <id>`。
3. 从安全详情取得 `linked_mods`、未知插件/材质/字体候选和角色候选。配置游戏版本由备份决定，不能在发布输入中另选。
4. 默认建议关联全部已识别插件；让用户决定哪些未知插件、材质和字体不随配置分享，并选择一个 `role_id`。不要从数量猜列表。

## 创建配置分享

需要：备份、标题、简介、正文及格式、至少一张图片、原创属性、公开选择、插件关联、三个忽略列表和角色。

1. 调 `config create`。未明确要求公开时 `public=false`。
2. 成功响应可能没有 ID；CLI 会尝试回查。仍没有 ID 时用未过滤的 `config list --page-size 100` 按标题、`cloud_id` 和更新时间确认，不能猜 ID。
3. 用 `config get` 核对标题、备份、图片、关联数量、角色和公开状态。

## 更新配置资料

1. 用 `config list`/`config get` 确认目标。
2. 只修改标题、简介、正文、图片等资料时，不提供 `cloud_id` 和备份关联字段。
3. 调 `config update`；该动作固定公开并可能重新审核。
4. 用 `config get` 确认未修改的图片、插件关联、忽略项和角色没有丢失。

## 切换云备份

1. 对新备份重新运行 `backup get`。
2. 必须同时提供 `cloud_id`、完整 `linked_mods`、`ignored_unknown_mods`、`ignored_materials`、`ignored_fonts` 和 `role_id`。不得沿用旧备份选择。
3. 调 `config update`，再读回核对新 `cloud_id`、关联数量、忽略项和角色。

配置更新成功响应可能为 `data=[]`，必须以 `config get` 的读回结果为准。
