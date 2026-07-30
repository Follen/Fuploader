# 新手盒子插件版本日志

## 目标

为插件版本文件提供独立的日志读取和编辑能力。编辑日志不创建版本、不上传压缩包、不改变插件元数据。

## CLI

- `fupload newbee plugin versions list`：列出插件版本文件及摘要。
- `fupload newbee plugin changelog list --mod-id <id>`：分页列出版本日志。
- `fupload newbee plugin changelog get --file-id <id>`：读取一个版本的完整日志。
- `fupload newbee plugin changelog edit --input <path|->`：编辑一个版本的日志。

所有命令支持 `--output human|json`；编辑支持 `--dry-run`。Skill 使用 JSON 输出，并在编辑前展示目标版本、旧日志摘要和新日志摘要。

## 服务端契约

| 动作 | endpoint | API 必传字段 | 条件/可选字段 |
| --- | --- | --- | --- |
| 列表 | `POST /creator/wow/mod_file/changelog_list` | `mod_id` | `pagenum`、`pagesize`；缺省使用稳定分页默认值 |
| 读取 | `POST /creator/wow/mod_file/get_changelog` | `file_id` | 无 |
| 编辑 | `POST /creator/wow/mod_file/edit_changelog` | `file_id`、`changelog` | 无 |

列表返回的版本文件 ID、版本、游戏版本和日志摘要必须规范化；读取/编辑不得输出 token 或下载地址。响应 `code != 1` 视为失败。

## 输入 schema

编辑输入必须带 schema 版本：

```yaml
schema: fupload.newbee.plugin.changelog.edit.v1
file_id: 557441
changelog: "修复接口兼容性"
```

`file_id` 为正整数，`changelog` 可为空字符串（表示清空日志），但字段必须存在；未知字段拒绝执行。

## 验收

- 列表、读取和编辑均映射到唯一 endpoint；编辑成功后再次读取能看到新日志。
- 编辑失败不报告成功；网络结果不确定时先重新读取，不自动重复编辑。
- 不生成删除命令，不调用 `/creator/wow/mod_file/remove` 或任何草稿接口。
