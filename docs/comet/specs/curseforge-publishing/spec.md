# CurseForge 作者发布

## 能力边界

Fuploader 将 CurseForge 作为与 NewBeeBox、DD 并列的平台。它读取 CurseForge 公共仓库中的 WoW Project，并向已存在的 WoW Project 上传新文件。它不创建 Project，不承诺通过公开 API 读取草稿或待审 Project。

## 本机配置

配置文件位于 `~/.fupload/curseforge.env`。npm postinstall、`fupload update` 和首次需要 CurseForge 配置的 CLI 路径均以非破坏方式确保该文件存在。已有文件不覆盖、不重排、不打印；卸载保留该文件。

配置只接受固定变量名 `CURSEFORGE_AUTHOR_ID`、`CURSEFORGE_API_KEY` 和 `CURSEFORGE_UPLOAD_TOKEN`。Core 查询所需的 API Key 与上传所需的 Upload Token 必须视为不同凭据。进程环境中的非空同名变量优先于固定文件，固定文件为空或缺失时报告具体缺少的变量名。真实秘密不得进入项目 JSON、仓库、日志、错误详情或标准输出。

## 项目查询

项目查询固定面向 World of Warcraft `gameId=1`，调用 CurseForge Core API：

```text
GET https://api.curseforge.com/v1/mods/search?gameId=1&authorId=<positive-integer>
x-api-key: <Core API Key>
```

命令从显式非秘密作者 ID 或固定配置读取作者 ID，从进程环境或固定配置读取 Core API Key。输出为 `fupload.output.v1`，至少包含 `author_id`、`total_count`、分页信息和脱敏后的项目数组。数组保留上传所需的 project ID、名称、slug、状态、创建/修改时间及相关安全元数据。查询只代表公开仓库状态。

## 游戏版本

CLI 通过 Upload API 的 `GET /api/game/versions` 获取当前可用 game version ID/name/type。上传输入中的 `gameVersions` 必须使用查询返回的 ID；`gameVersionNames` 按官方字段契约透传并进行类型校验。

## 插件包上传

上传固定调用：

```text
POST https://wow.curseforge.com/api/projects/<projectId>/upload-file
X-Api-Token: <Author Upload Token>
Content-Type: multipart/form-data
```

multipart 必须包含 JSON 字符串字段 `metadata` 和本地文件字段 `file`。metadata 支持官方文档中的 changelog、changelogType、displayName、parentFileID、gameVersions、gameVersionNames、releaseType、isMarkedForManualRelease 和 relations.projects。CLI 对枚举、正整数、数组对象结构、条件互斥与 ZIP 文件存在性实施严格校验。

dry-run 不读取凭据、不发网络请求，输出 schema 和本地文件摘要。live 上传只发送一次；成功必须返回正整数 file ID。HTTP 明确拒绝可安全报告失败，连接中断或响应不确定标记 `verification_required=true` 且不自动重传。官方 Upload API 未公开文件读回端点时，响应 file ID 是本次 API 操作的确认，Skill 必须把审核/公开状态描述为待平台处理而不是已公开。

## Skill 编排

用户明确选择 CurseForge 上传时，Skill 加载 CurseForge reference，检查固定配置和所需环境变量。缺少作者 ID 时主动询问；缺少秘密时要求用户在本机填写 `~/.fupload/curseforge.env` 或预先注入进程环境，不要求把 Token/Key粘贴到对话。

Skill 使用项目查询选择目标 Project，读取 game version 候选，检查插件 ZIP 和 metadata，创建版本化发布计划，先执行 dry-run，再展示完整计划并获得明确确认。写入后记录返回 file ID 和平台处理状态。失败或不确定结果遵守现有 Fuploader 停止、脱敏与最小重试规则。

## 安装与生命周期

npm 安装器创建 `.fupload` 目录和缺失的 `curseforge.env` 模板，模板包含三个固定变量名和空值。安装和更新不提示输入秘密、不覆盖已有文件。目录与文件在 POSIX 使用仅当前用户可读写的权限；Windows 使用用户 home 范围且不放宽继承权限。安装、更新和首次启动均幂等。npm 包、Skill manifest 和全局安装烟测覆盖新增 reference/provider 文件。完整卸载移除托管 Skill 和 npm 命令，但保留 `.fupload/curseforge.env`。

## 验证

测试必须覆盖 schema、CLI help、项目查询请求、上传 multipart、配置解析、优先级、脱敏、网络错误、安装初始化/保留、更新/卸载保留以及打包清单。Skill Creator 校验必须通过，且前向测试能够仅依据 Skill 与 reference 正确规划查询和上传。
