# ModUs / CurseForge 字段核对输入

核对日期：2026-10-30。完整字段投影、条件、证据和已知缺口见同目录 `modus-curseforge.json`。该 JSON 覆盖当前 ModUs 245 个、CurseForge 11 个注册输入字段，并另列状态对象内字段及读取动作。本机控制字段明确记录不发接口；字段名枚举来自实现，平台语义另由官方源码、官方 IL 或官方文档支持。

## ModUs

Creator 证据来自官方 DLL 0.1.6.0 的 IL；主客户端提取包的 package.json 标记 1.2.9。旧 API 汇总中 project delete 的 GET、release detail 的双 ID 路径与 IL 不符，本次采用 IL。Creator 官方为 Bearer 认证，已有 Bearer 前缀不重复添加；主客户端发送存储 token 原样。修复后分别使用现有 Creator 与主客户端登录来源，各读取 Creator 项目列表和主客户端云备份列表，四次读取均被接受。这只记录这两套现有来源的读取结果。

2026-10-31 补核当前安装 Creator/Shared 0.1.9.0：项目状态 1/2/3 对应已通过/待审核/已拒绝，创建可直接返回已通过；不存在已证实的项目私密或草稿控制。官方 CanCreate 拒绝空发布平台，Alpha/Beta 只是版本类型。真机新建空项目未进入公共列表，首个合成 Alpha 版本发布后匿名可见；本轮临时项目及版本均已删除，原项目记录哈希保留。

当前 Creator 下载按钮使用 CdnService.Resolve(release.path)。真机确认旧默认本机 ZIP 名会生成 404 下载地址；同一文件的官方对象路径可下载且字节一致。默认路径现为 modus/wow/addons/{projectId}/files/{fileId}.zip，显式路径保留，上传及路径修改后校验同 fileId 保存的路径、MD5、尺寸和实际 CDN 包；下载不符返回 verification_required，不重放 metadata 或 PUT。版本 changelog 清空也按当前官方 NullMarkerIfWhiteSpace 使用 `<null>`，真机已确认 null/空白清空及非空原文保留。

同 fileId 二进制更新已做冷、热缓存对照：本轮客户端首次访问 CDN 前完成覆盖，新 ZIP 的完整字节、MD5 和尺寸均通过；已有下载缓存的地址八小时后复查仍返回旧包。记录和 PUT 已是新内容时，CDN canonical 地址仍可能继续返回旧 ZIP。原有顺序和官方 PUT 后登记 metadata 的顺序均复现，no-cache 请求未消除旧缓存。没有从当前官方客户端找到可用的作者 CDN 刷新接口；因此保留待核验，不加入 cachebusting query，也不把另建 fileId 的独立版本偷偷作为 update。结构化证据记录期望/实际摘要、尺寸和响应 Age。

配置分享 `content` 是公开富文本存储内容，图片替换成资源键标记；`contentText` 是公开纯文本。真实 detail 响应不返回 contentText；稀疏编辑会按官方 Q2 的 DOM textContent 规则从正文恢复，去除 WA/图片占位及脚本等隐藏节点，HTML 本身原样保留。明确更改正文而未给纯文本时，同步重新计算。WA 导入串由独立的 `codeText` 传输。官方编辑器保存时生成 HTML、存储 content、plainText 三份表示；读取兼容旧 Base64 内容，当前保存链没有再次 Base64 编码。IO 应按资源和字段语义区分公开正文与导入串。

本次已修复多处已有功能问题：Creator 发布文件的 metadata-only `md5` / `zip_size` / `unzip_size` 被丢弃和 `changelog:null` 被静默过滤；主客户端稀疏编辑重置 platform / excludeWtf / synchronizationType；读取 `--page` 没有映射实际页码；项目列表把 CLI envelope 参数带入请求。稀疏编辑现在先读当前 detail，再从允许字段重建完整提交体；创建默认值只用于新建。没有官方 null 清空证据的正文、角色等字段显式拒绝 null；订阅等级的 null 按官方完整表单省略 requiredTierId。

完成 project_state 现作为 license / publish_platforms 的规范来源：相同顶层值兼容，冲突在请求前拒绝；其他顶层元数据覆盖后重新执行状态机分类、平台、订阅等级和同步类型校验。

受限项目规则已补齐：`0 < project_id < 200000000` 的项目编辑先读取当前 detail，拒绝修改名称、仓库、平台、分类、订阅等级、依赖、许可证或图片，只提交官方允许的别名、简介、正文。删除项目和修改发布版本在 schema、dry-run、provider 均拒绝。

赛季订阅已接入 `GET /user/game-type/list` 和 `GET /user/author/season-sub/detail?authorId=...&gameType=...`；后者按官方设置不发 X-Server-Type。新增 `options subscription-game-types` 与 `options season-subscription --game-type <gameCode> [--author-id ID]`。选择赛季订阅时独立核对本人、当前游戏、ID、启用及结束状态。现有主客户端登录只读验证通过：游戏候选包含 wow_retail / wow_classic_titan，本人正式服当前无赛季候选，输出 null。

config / WA create 现已从 schema 移除编辑 ID，provider 同样明确拒绝。M-RESTRICTED、M-SEASON、M-CREATE-ID 均记录完成状态。作者订阅等级保存、Creator 二维码登录等平台能力尚无对应 CLI，继续在结构化审计中单列。

ModUs 五个 Build（0 至 4）均以仅合成内容完成生成、上传、改名、删除和读回，原有备份保留。正式服临时私密配置完成创建、长 HTML 编辑及图片/备份关联保留，2368 字符正文完整读回；关联备份在 confirm_delete=true 下拒删，先删配置再删备份后均确认消失。测试备份 4540、431、259、1557、443 及私密配置已清理。

实际接口验证发现 backup list 的请求分支头不足以证明返回行归属。预览按详情中的有效整数 serverType 过滤，错分支/缺失身份拒绝；删除扫描全部五个 Build 的分享分页及详情，跨分支关联也保护。DELETE 的 HTTP 5xx 或 2xx 坏 JSON 均报告结果不确定，不自动重放。关联补查必须核对请求身份。

## CurseForge

[官方上传 API 文档](https://support.curseforge.com/support/solutions/articles/9000197321)说明 multipart 元数据、发布版本和依赖关系字段；[Core REST 官方文档](https://docs.curseforge.com/rest-api/)说明搜索分页与作者筛选。Core 的 authorId 筛选项目成员，primaryAuthorId 才筛选主要作者。现有作者项目列表使用前者。

作者列表原本只获取首 50 项，现已逐页读取，并检查稳定总数、页码、返回计数、重复 ID 和提前空页；达到官方 10000 索引边界而未完成时明确报错，不返回完整假象。缺少总数的响应继续读取至空页。

平台已有 `POST /api/projects/{projectId}/update-file` 修改文件元数据能力，Fupload 本次没有增加该写入动作。依赖项发现和 Core 文件详情 / changelog 查询也仅列为平台能力缺口。上传接口返回文件 ID 表示服务器接受，不代表审核或后续处理完成；当前工具没有相应状态读回。

## 本地验证

ModUs 测试覆盖官方认证格式、读取页码、请求字段隔离、稀疏编辑保留完整表单、null 条件、文件摘要与尺寸透传，以及备份只打包显式选择的角色。CurseForge 测试覆盖跨 50 条分页、重复页、提前终止、索引上限和无总数分页。自动化测试使用本地 mock；ModUs 的真实备份及私密分享验收见上节，CurseForge 本轮未调用真实写入。
