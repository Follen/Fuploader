# NewBee WA/字符串完整链路目标规格

## 命令与原子语义

NewBee WA 提供 list/get/categories/attachment-paths、create/update/edit、media upload、
changelog latest/list/get/edit、co-author search/list/set、reference search/list/set 和
share-code set。`update` 发布字符串新版本，`edit` 只改元数据与设置；附属动作独立重试。

## 全部字段

create/edit 元数据覆盖 `game_version_id`、`name`、`intro`、`description`、
`content_format`、`thumbnail`、`images`、`category_id_list`、`content_origin`、
`subscribe_plan_level`、`price`、`time_range`、`share_state`、`link_to_channel`、
`attachments`；edit 增加 `id`。create 的 description、分类和封面必填，WA 私有值为 2、公开值为 1。

附件完整字段为 `name/install_type/install_path/value/is_compressed/timestamp?`。本地封面、
图片和附件材质可通过明确上传步骤取得远端引用；安装类型/路径用动态接口验证。上传成功但
主动作失败时报告孤立媒体引用，不重复上传。

create 另含 `wa_str`、`wa_str_titles`、`wa_log`、`string_mode`。单条模式发送原始字符串；
合集模式发送字符串数组 JSON 和同序标题。update 固定执行 get_next_version 后调用
update_wa_str，字段为 `id/version/wa_str/wa_str_titles/wa_log/link_to_channel`。
edit 不得携带字符串版本字段。

日志编辑只修改指定记录 `wa_log`；共创项为 `user_id/share_percent`，总比例不超过 1；
引用项为 `type/id`；分享码固定 NewBee WA module 语义。任何附属失败均保留主对象 ID。

## 安全与验证

create/update/edit 输入使用独立版本化 schema，未知字段和错误阶段字段本地拒绝。edit 先
读取当前详情并按字段存在性合并。普通输出不含原始 WA 字符串、凭据或临时 URL，只返回
长度/哈希摘要。写后从详情、最新版本或日志接口读回；不提供删除或草稿命令。
