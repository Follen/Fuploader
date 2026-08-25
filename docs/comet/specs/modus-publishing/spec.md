# ModUs 插件发布

## 目标

Fupload 提供 `modus` 平台的插件作者工作流，复用本机 ModUs.Creator 登录态，覆盖插件项目、发布版本和 ZIP 上传的完整生命周期。

## 认证

- 读取 `%LOCALAPPDATA%\ModUs.Creator\auth\token.dat`。
- 使用 DPAPI `CurrentUser` 和 UTF-8 熵 `ModUs.Creator.TokenStore.v1` 解密。
- 每个 API 请求发送 `Authorization: Bearer <token>`。
- 诊断输出只包含文件存在、解密成功和 token 非空状态，不包含 token、cookie 或密文。

## 读取能力

- 作者项目列表、项目详情、项目发布文件列表和发布文件详情。
- 插件动态分类、游戏版本及服务端返回的项目/版本字段。
- 发布状态、文件 ID、版本、MD5、ZIP/解压大小、TOC 版本、支持游戏版本、变更日志和下载统计。

## 项目状态机与全字段契约

创建/编辑项目必须按 Creator 的状态机校验：

1. 选择游戏：当前 WoW 游戏对象必须可回读；步骤未完成时不能提交后续步骤。
2. 基本信息：名称、别名、摘要、分类、同步类型、发布平台、订阅等级、仓库地址、图片/截图等字段按服务端规则提交。
3. 许可证：模板、版权所有者、版权年份、许可证正文组成许可证对象或服务端要求的 JSON 字符串。

平台规则：`publishPlatforms` 至少包含一个平台；`ModUs` 和 `BigFoot` 允许同时存在，不互斥。当前账号的 Creator 订阅等级下拉只有“无”，服务端动态接口返回空数组，因此 `requiredTierId` 必须为 JSON null，编辑清空时使用 Creator 的 `<null>` wire 标记。BigFoot 组合也必须为 null；不得构造不存在的付费等级或收益分支。

分类必须使用服务端分类枚举/对象的真实 wire 表示，不能把展示文字直接当作 ID。每个项目字段都必须在文档和 schema 中记录：CLI 名称、wire 名称、JSON 类型、必填/可选、默认值、枚举或下拉来源、状态机依赖、互斥/至少一项约束、成功回读字段。未知类型保持阻塞，直到 IL、成功客户端请求或真实回读证据确认。

当前已确认的项目详情字段包括：`projectId`、`name`、`altName`、`summary`、`categories`、`synchronizationType`、`license`、`images`、`logo`、`repoUrl`、`requiredTierId`、`requiredDependencies`、`cfUrl`、`status`。创建请求还需覆盖 `screenshotBase64sReqs` 及其图片名/内容结构；实际 JSON 类型和空值规则以成功流量或回读为准。

## 写入能力

- 创建、编辑、删除作者项目。
- 分配发布文件 ID。
- 创建发布元数据；更新发布元数据。
- 获取签名上传 URL，并将本地 ZIP 原始字节上传到该 URL。
- 删除指定发布文件。
- 所有写操作必须使用版本化 JSON、显式正整数 ID 和回读校验。
- 项目每个可编辑字段必须执行单字段修改、回读、原值恢复、再次回读；字段之间的联动、下拉枚举、至少一项和空值分支必须各有真实记录。当前账号的 tier 下拉空枚举和 `requiredTierId=null` 即完整真实分支。

## 上传事务

1. 校验 ZIP 并计算 `md5`、`zipSize`、`unzipSize`、`tocVersion` 和支持游戏版本。
2. 请求项目文件 ID。
3. 提交 `projectId`、`version`、`type`、`supportedGameVersionsReqs`、`md5`、`zipSize`、`unzipSize`、`path`、`tocVersion`、`changelog`。
4. 获取 `signedUrl`。
5. 上传 ZIP 二进制；不得把本地路径当作二进制上传的替代品。
6. 读取发布详情或列表确认服务端记录和文件状态。

## CLI 契约

- `fupload modus session doctor`
- `fupload modus project list|get|create|edit|delete`
- `fupload modus plugin list|get|versions|create|upload|update|edit|delete`
- `fupload modus options categories|game-versions`
- 写操作沿用现有 JSON schema、`--input`、`--dry-run` 和脱敏错误输出契约。

## 真实测试

使用专用测试项目和最小合法 ZIP，依次执行登录态诊断、作者项目列表/详情、动态选项、项目创建、项目全字段详情回读、每个字段单独修改/回读/恢复、平台与订阅状态机分支、插件创建/上传、详情回读、版本更新、元数据编辑、发布删除、项目删除。测试结束后必须回读确认删除；报告保存命令、脱敏请求摘要、响应摘要和退出码，不保存认证材料或签名 URL。真实回归必须覆盖最早 change 的全部已确认接口和 CLI，不得以 dry-run 或单元测试替代真实请求。

## 发布门禁

只有以下条件全部完成，change 才可验收：

- ModUs 全字段 API 契约、状态机和真实回归矩阵均有证据；失败步骤保留事务记录并明确阻塞。
- 最早 change 的登录态、项目、插件、上传、更新、删除、清理和回读全量测试通过。
- 运行完整本地测试、打包检查和安装检查；版本号、manifest 和 npm 包内容一致。
- 将已验证提交推送到 GitHub `origin` 目标分支，并记录提交哈希和推送结果。
- 使用 `npm publish --access public` 发布 `@follenfang/fupload`，记录版本和 registry 回读结果；未完成 GitHub 推送或 NPM 发包不得进入 Archive。

## 错误与回滚

- 上传任一阶段失败时保留本地 ZIP 和事务记录，禁止假报成功。
- 远端写操作失败时输出阶段、端点和脱敏响应摘要。
- 清理流程按发布文件、插件项目顺序执行，并在每步回读；清理失败必须标记为阻塞。
