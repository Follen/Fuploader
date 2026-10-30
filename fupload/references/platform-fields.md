# 平台字段与登录契约

核对日期：2026-10-30。此表覆盖 Fupload 作者发布、配置分享、WA 与云备份命令，不把客户端其它业务算作已支持。

当前共 **88 个写入动作、731 个动作字段位置**。字段在不同动作中出现时分别列出，必填性可能不同。

本文件由 `tools/build_platform_fields.py` 根据可执行 Schema、CLI 命令树和 `docs/platform-audit/*.json` 的协议核对记录生成。修改字段后运行生成器；`--check` 检查是否同步。

## 使用规则

- 写命令使用 `--input <JSON文件>|-`；首项 `schema` 必须与动作完全匹配。`--dry-run` 只核对本机结构，不执行登录、上传或远程验证。
- 必填、允许 null 和条件必填是不同概念。省略字段的含义由动作决定；不要将省略一律替换成空字符串、空数组或 false。
- 备份 ID、插件 ID、版本 ID、配置 ID 及本地备份 ID 分开使用。动态版本、分类、套餐、账号角色和频道先查询，不照抄历史编号。
- 备份删除必须使用明确 ID 与 `confirm_delete=true`。已被配置分享引用的备份禁止删除；查询不完整时停止。
- 手机号、验证码、Cookie、pkey、token、签名上传地址不进入输出、样例或版本库。登录待办只返回不透明任务编号、状态和二维码图片路径。

## 平台索引

- [新手盒子](#newbee)
- [网易 DD](#dd)
- [黑盒工坊](#blackbox)
- [ModUs 与 Creator](#modus)
- [CurseForge](#curseforge)

<a id="newbee"></a>
## 新手盒子

审计日期：2026-10-30。机器可读结果见 `docs/platform-audit/newbee.json`：当前 Python 写入 schema 的 186 个字段均有对应的 wire、阶段、条件和来源；类型、必填项和结构约束以 `fupload_cli.schema.SCHEMAS` 为准。

证据分别来自已保存的 Creator Center 网页资源、本机官方桌面客户端 1.1.29、本机 NCC 0.1.29，以及本轮有限的真实备份测试。网页快照有具体资源文件名，未将其版本声明为最新。桌面版本取自 `app.asar/package.json`；注册表显示名仍为旧版本。

### 配置分享正文与选择项

`config.content` 是公开展示的富文本描述，可以是 HTML 或 Markdown。Creator 表单将编辑器的 `content` 发送为同名字段，桌面客户端将详情的 `t_content` 还原到富文本编辑器。它与 `cloud_id`、`linked_mods`、`ignored_unknown_mods`、`ignored_materials`、`ignored_fronts`、`roleid` 所选择的备份数据分开。配置详情应保留描述全文；WA 原始字符串和备份原始内容继续遵循各自的输出规则。

当前桌面客户端和 NCC 的配置发布体均发送固定的 `selected_eml: []`。桌面读取 `t_selected_eml` 并扫描 `editModeLayouts`，但新建非空选择对象的结构尚未确认。Python schema 没有这个字段，也不猜测其对象结构。已有布局现已作为服务端对象完整读出，在配置 `edit/update` 时保留原数组及全部嵌套字段，并加入写后回读检查；异常的非数组值会在写入前停止。这项保留行为已有本地回归，尚无现成布局配置可供远程写入验证。

Python 配置的 `linked_mods` 以选中备份的实际插件条目为准。调用者选择 `mod_id`，版本、文件和更新方式由实时备份条目规范化，不能把它当作任意插件版本覆盖入口。联合作品和引用关系使用独立接口；省略保留，显式空数组清空，主记录写入与回读完成后才替换关系。

### Python 与 NCC 的实际差异

| 能力 | Python 通道 | NCC 0.1.29 |
| --- | --- | --- |
| 插件官网 | schema 没有 `home_page`、`home_page_link` | `addons create` 有 `--home-page`、`--home-page-link`；编辑命令未列出这两个参数 |
| 插件首建公开状态 | 先以 `share_state=0` 创建，上传首个版本后再编辑为公开 | 包装接口以 2 表示私密、1 表示公开；数值不能直接移植 |
| 插件版本文件 | 已有 ZIP、RAR、7z，最大 300 MiB，明确给出游戏构建列表 | `pack`/`push` 面向本地插件目录，有 TOC 检测、忽略和打包流程，最大 2048 MiB |
| 配置发布 | 支持已验证的备份插件、忽略项和角色选择数组 | `uipack publish` 暴露备份、角色等参数，未暴露所有细粒度选择；部分数组由备份生成 |
| WA | 单条、集合、有序标题及附件 | CLI 以单条字符串为主；集合和附件留在网页流程 |
| 价格单位 | JSON 整数分 | 命令参数为元，CLI 转成分 |
| 云备份 | 本地扫描、生成、上传、创建、改名、预览和受保护删除 | `cloudbackup list/info`；上传和恢复指向桌面客户端 |
| 主记录删除 | Python 有插件、配置、WA 的删除接口 | NCC 提示前往网页删除 |

`newbee.json` 保存了 31 个相关 NCC 叶子命令的全部帮助参数。官方 CLI 的能力不自动成为 Python JSON 字段；Python 也不会在缺少能力时静默切换到 NCC。

### 云备份协议与选择约束

本机桌面客户端的 `js/8761.js` 与 `js/app.js` 模块 29474 确认备份清单和 `/v3/share/create`、`/v3/share/list`、`/v3/share/delete`、`/share/update`、`/share/generate_upload_url_v2`。已保存的旧桌面资源 `2261.js` 不是本机当前资源名。来源文件的 SHA-256 写入 JSON，便于以后比对。

已知插件只写入 `knowplug_list` 元数据；未知插件、材质和选中的 WTF 内容分别压缩，字体使用官方原生 `OssUploader.uploadFolder` 取得哈希和清单。账户通用包只包含账户根文件及 `SavedVariables`，角色包只包含对应角色根。上传前校验清单与归档选择一致，并拒绝路径逃逸、链接和大小写折叠后重复条目。修改 JSON 里的角色名而保持原 ZIP 不变，会在远程请求前被拒绝。

`scan` 返回本地候选目录，没有复现官方插件识别服务及本地锁文件查找。它不能仅凭文件夹名生成官方已知插件 ID。调用者提供的 `known_plugins` 必须包含已核实的完整插件条目。

备份删除先遍历本人配置分享并确认所有关联。任意 `cloud_id` 引用都会拒删；分页不完整或关联未知同样拒删。执行前再次检查，单次发送删除后读回确认，不重放结果不确定的写入。

### 验证范围

2026-10-30，真实 Python 通道使用只含合成 `FuploadBackupProbe.toc` 的未知插件包，在 `game_version_id=2` 完成生成、签名上传、创建、改名、删除预览、单次删除及列表回读。初次临时备份 ID 4141994 已删除。

这次真实上传确认：历史签名返回的 OSS HTTP 地址升级到 TLS 后可用；PUT 的 `Content-Type` 必须为签名所要求的 `application/x-www-form-urlencoded`。不带此头或改成二进制类型返回 403，匹配后返回 200。

之后又完成两条合成备份的批量流程。ID 4142385 包含未知插件、材质、一个合成字体、两个账户及两个选中角色，使用 5 个 ZIP 和官方原生字体上传；ID 4142386 只含未知插件。两条均通过创建及改名回读、完整预览、批量删除和负向列表回读。

动态版本接口返回的 7 个分支为无限（9）、正式服（2）、泰坦重铸（4）、熊猫人之谜（7）、燃烧的远征（8）、经典旧世（6）、探索赛季（3）。每个分支的分类只读查询成功。其余 6 个分支各生成一条最小未知插件备份，完成上传、游戏分支读回、改名，最后批量删除；测试 ID 4142398 至 4142403 均已清理。

真实正向关联保护也已通过：新建含合成 WTF 角色的备份 4142419，使用详情中的实际角色 ID 和 640×360 合成 PNG 创建私密配置 62433，读回确认 `public=false`。关联预览拒删，传入 `confirm_delete:true` 仍拒删，拦截计数确认实际删除接口调用为 0。随后先删除配置并读回，再删除已解除关联的备份并读回。此前失败的最小配置请求没有重放；另一条在本地 schema 校验中发现数值角色 ID 的测试备份 4142416 也已清理。

服务端备份详情的角色 ID 实际为数值，现已在查询输出中统一转为配置 schema 所需的字符串。42 项 NewBee 定向测试通过，包括 162 个旧 Creator schema 字段案例、新增布局保留、角色 ID 类型和权限错误回归。本地测试另覆盖关联分页、详情补查、批量整体拒绝、执行前再次检查及不确定结果停止。最终账号配置扫描为 0，原有两个备份全部保留，没有发布新的公开插件、配置或 WA。平台服务端是否原子保护关联仍未验证，客户端硬拒删已有真实证据。

### 官方 NCC 命令参数

本机只读核对版本：`0.1.29`。以下是官方 CLI 的独立入口，不能当作 Python JSON 字段使用。完整位置参数与配置说明见 [NCC 官方文档快照](newbee-official-cli.md)。

| 官方命令 | 参数 | 含义 |
| --- | --- | --- |
| `ncc wow addons list` | `--keyword <kw>` | 搜索关键词（匹配插件名称/描述） |
| `ncc wow addons list` | `--pagenum <n>` | 页码（等同位置参数写法） |
| `ncc wow addons list` | `--pagesize <n>` | 每页数量（10-2000） |
| `ncc wow addons info` | 无额外选项 | 位置参数见官方快照 |
| `ncc wow addons init` | `--id <mod_id>` | 插件 ID（ncc wow addons list 查询） |
| `ncc wow addons init` | `--refresh-config` | 强制刷新客户端版本分组缓存 |
| `ncc wow addons push` | `--id <mod_id>` | 插件 ID（缺省读 ncc.json） |
| `ncc wow addons push` | `--version <v>` | 版本名（自由文本，同插件内不可重复；缺省读 ncc.json） |
| `ncc wow addons push` | `--changelog <text\|@file>` | 更新日志（@file 从文件读；缺省读 ncc.json 的 changelog_file） |
| `ncc wow addons push` | `--game-versions <spec>` | 适配客户端版本：显式版本串(11.2.7,12.1.0)/auto=.toc 检测（缺省读 ncc.json） |
| `ncc wow addons push` | `--dry-run` | 只校验参数+打包预检，不上传 |
| `ncc wow addons push` | `--refresh-config` | 强制刷新客户端版本分组缓存 |
| `ncc wow addons create` | `--name <name>` | 插件名称 |
| `ncc wow addons create` | `--description <text\|@file>` | 插件详情正文（Markdown，@file 从文件读） |
| `ncc wow addons create` | `--categories <ids>` | 分类 ID，逗号分隔（查询：ncc wow addons categories） |
| `ncc wow addons create` | `--logo <file\|url>` | 插件图标（本地图片路径或已上传链接） |
| `ncc wow addons create` | `--screenshots <items>` | 插件截图，逗号分隔（本地图片路径或已上传链接） |
| `ncc wow addons create` | `--intro <text>` | 一句话简介（缺省从正文自动提取） |
| `ncc wow addons create` | `--home-page <name>` | 官网名称 |
| `ncc wow addons create` | `--home-page-link <url>` | 官网链接（http 开头） |
| `ncc wow addons create` | `--private` | 私密发布（默认公开；公开内容进入平台审核） |
| `ncc wow addons create` | `--origin <type>` | 内容来源：original 原创 / repost 转载 / localized 汉化 (default: "original") |
| `ncc wow addons create` | `--subscribe-level <n>` | 订阅计划等级（需已开通对应订阅计划） |
| `ncc wow addons create` | `--link-channel` | 发布后自动推送动态到社区频道 |
| `ncc wow addons edit` | `--name <name>` | 插件名称 |
| `ncc wow addons edit` | `--description <text\|@file>` | 插件详情正文（Markdown，@file 从文件读） |
| `ncc wow addons edit` | `--intro <text>` | 一句话简介（传空串 "" 则从正文重新提取） |
| `ncc wow addons edit` | `--categories <ids>` | 分类 ID，逗号分隔（查询：ncc wow addons categories） |
| `ncc wow addons edit` | `--logo <file\|url>` | 插件图标（本地图片路径或已上传链接） |
| `ncc wow addons edit` | `--screenshots <items>` | 插件截图，逗号分隔（本地图片路径或已上传链接，整组替换） |
| `ncc wow addons edit` | `--private` | 设为私密 |
| `ncc wow addons edit` | `--public` | 设为公开（公开内容进入平台审核） |
| `ncc wow addons edit` | `--subscribe-level <n>` | 订阅计划等级（0=取消订阅门槛，需已开通对应订阅计划） |
| `ncc wow addons edit` | `--link-channel` | 本次编辑推送动态到社区频道 |
| `ncc wow addons pack` | `--version <v>` | 版本号（用于输出文件名；缺省读 ncc.json） |
| `ncc wow addons pack` | `--out <path>` | 输出 zip 文件或目录（默认当前目录，文件名 <目录名>-<版本号>.zip） |
| `ncc wow addons sync` | `--yes` | 确认覆盖本地内容文件 |
| `ncc wow addons versions` | `--id <mod_id>` | 插件 ID |
| `ncc wow addons versions` | `--pagenum <n>` | 页码（等同位置参数写法） |
| `ncc wow addons versions` | `--pagesize <n>` | 每页数量（10-2000） |
| `ncc wow addons changelog` | `--set <text\|@file>` | 新的日志内容（@file 从文件读；不传则查看） |
| `ncc wow addons game-versions` | 无额外选项 | 位置参数见官方快照 |
| `ncc wow addons categories` | `--refresh-config` | 强制刷新分类缓存 |
| `ncc wow addons comments` | 无额外选项 | 位置参数见官方快照 |
| `ncc wow wa list` | `--keyword <kw>` | 搜索关键词（匹配名称/简介） |
| `ncc wow wa list` | `--paid` | 只看付费内容 |
| `ncc wow wa list` | `--free` | 只看免费内容 |
| `ncc wow wa info` | 无额外选项 | 位置参数见官方快照 |
| `ncc wow wa init` | `--id <wa_id>` | 字符串 ID（ncc wow wa list 查询） |
| `ncc wow wa pull` | `--out <path>` | 输出文件（默认 wa_<ID>_v<版本>.txt） |
| `ncc wow wa push` | `--file <path>` | 字符串内容文件（如 pull 拉取后编辑的文件） |
| `ncc wow wa push` | `--log <text\|@file>` | 更新日志（@file 从文件读） |
| `ncc wow wa push` | `--version <v>` | 新版本号（1.2.3 形式，须大于当前版本；缺省自动递增） |
| `ncc wow wa publish` | `--name <name>` | 字符串名称 |
| `ncc wow wa publish` | `--description <text\|@file>` | 字符串描述正文（Markdown，@file 从文件读） |
| `ncc wow wa publish` | `--wa-str <text\|@file>` | 导出的字符串内容（建议 @file 从文件读） |
| `ncc wow wa publish` | `--game-version <id\|名称>` | 游戏版本（如 2 或 正式服） |
| `ncc wow wa publish` | `--categories <ids>` | 分类 ID，逗号分隔，至多 5 个（查询：ncc wow wa categories --game-version X） |
| `ncc wow wa publish` | `--thumbnail <file\|url>` | 展示图（本地图片路径或已上传链接） |
| `ncc wow wa publish` | `--images <items>` | 预览图，逗号分隔（本地图片路径或已上传链接） |
| `ncc wow wa publish` | `--changelog <text\|@file>` | 更新日志 |
| `ncc wow wa publish` | `--intro <text>` | 一句话简介 |
| `ncc wow wa publish` | `--private` | 私密发布（默认公开；公开内容进入平台审核） |
| `ncc wow wa publish` | `--price <元>` | 单项付费价格，单位元（付费内容需人工审核） |
| `ncc wow wa publish` | `--subscribe-level <n>` | 订阅计划等级（需已开通对应订阅计划） |
| `ncc wow wa publish` | `--time-range <r>` | 订阅有效时间范围 |
| `ncc wow wa publish` | `--origin <type>` | 内容来源：original 原创 / repost 转载 / localized 汉化 (default: "original") |
| `ncc wow wa publish` | `--link-channel` | 发布后自动推送动态到社区频道 |
| `ncc wow wa publish` | `--refresh-config` | 强制刷新游戏版本缓存 |
| `ncc wow wa edit` | `--name <name>` | 字符串名称 |
| `ncc wow wa edit` | `--description <text\|@file>` | 字符串描述正文（Markdown，@file 从文件读） |
| `ncc wow wa edit` | `--intro <text>` | 一句话简介 |
| `ncc wow wa edit` | `--categories <ids>` | 分类 ID，逗号分隔，至多 5 个（查询：ncc wow wa categories --game-version X） |
| `ncc wow wa edit` | `--thumbnail <file\|url>` | 展示图（本地图片路径或已上传链接） |
| `ncc wow wa edit` | `--images <items>` | 预览图，逗号分隔（本地图片路径或已上传链接，整组替换） |
| `ncc wow wa edit` | `--private` | 设为私密 |
| `ncc wow wa edit` | `--public` | 设为公开（公开内容进入平台审核） |
| `ncc wow wa edit` | `--price <元>` | 单项付费价格，单位元（0=取消单项付费；付费内容需人工审核） |
| `ncc wow wa edit` | `--subscribe-level <n>` | 订阅计划等级（0=取消订阅门槛，需已开通对应订阅计划） |
| `ncc wow wa edit` | `--link-channel` | 本次编辑推送动态到社区频道 |
| `ncc wow wa categories` | `--game-version <id\|名称>` | 游戏版本（如 2 或 正式服） |
| `ncc wow wa categories` | `--refresh-config` | 强制刷新游戏版本缓存 |
| `ncc wow wa comments` | 无额外选项 | 位置参数见官方快照 |
| `ncc wow uipack list` | `--keyword <kw>` | 搜索关键词（匹配分享码/标题） |
| `ncc wow uipack list` | `--paid` | 只看付费内容 |
| `ncc wow uipack list` | `--free` | 只看免费内容 |
| `ncc wow uipack info` | 无额外选项 | 位置参数见官方快照 |
| `ncc wow uipack init` | `--id <config_id>` | 配置 ID（ncc wow uipack list 查询） |
| `ncc wow uipack pull` | `--out <path>` | 输出文件（默认 uipack_<ID>.md，HTML 格式为 .html） |
| `ncc wow uipack push` | `--file <path>` | 正文内容文件（Markdown；HTML 存量请走网页端） |
| `ncc wow uipack push` | `--title <text>` | 新标题 |
| `ncc wow uipack push` | `--intro <text\|@file>` | 新摘要（@file 从文件读；不传且更新了正文时自动从正文提取） |
| `ncc wow uipack publish` | `--backup <backup_id>` | 云端备份 ID |
| `ncc wow uipack publish` | `--title <title>` | 标题 |
| `ncc wow uipack publish` | `--content <text\|@file>` | 正文（Markdown，@file 从文件读） |
| `ncc wow uipack publish` | `--images <items>` | 展示图，逗号分隔，至少一张（本地图片路径或已上传链接） |
| `ncc wow uipack publish` | `--role <roleid>` | 分享的角色数据 ID（缺省不指定） |
| `ncc wow uipack publish` | `--intro <text>` | 自定义摘要（缺省从正文自动提取） |
| `ncc wow uipack publish` | `--private` | 私密发布（默认公开；公开发布需认证作者，内容进入平台审核） |
| `ncc wow uipack publish` | `--price <元>` | 价格，单位元（默认免费） |
| `ncc wow uipack publish` | `--subscribe-level <n>` | 订阅计划等级（需已开通对应订阅计划） |
| `ncc wow uipack publish` | `--time-range <r>` | 订阅有效时间范围 |
| `ncc wow uipack publish` | `--origin <type>` | 内容来源：original 原创 / repost 转载 / localized 汉化 (default: "original") |
| `ncc wow uipack publish` | `--link-channel` | 发布后自动推送动态到社区频道 |
| `ncc wow uipack comments` | 无额外选项 | 位置参数见官方快照 |
| `ncc wow cloudbackup list` | 无额外选项 | 位置参数见官方快照 |
| `ncc wow cloudbackup info` | 无额外选项 | 位置参数见官方快照 |

依据：本机官方 NCC 各叶子命令 `--help`，未触发登录或业务写入。

### 只读命令与输入参数

| 命令 | 参数 | 默认/必填 |
| --- | --- | --- |
| `newbee backup list` | 无额外参数 | — |
| `newbee backup get` | `--id/--backup-id` | 必填 |
| `newbee backup scan` | `--game-dir` | 必填 |
| `newbee backup delete-preview` | `--backup-ids` | 不传 |
| `newbee backup delete-preview` | `--name-contains` | 不传 |
| `newbee backup delete-preview` | `--name-equals` | 不传 |
| `newbee backup delete-preview` | `--created-before` | 不传 |
| `newbee backup delete-preview` | `--created-after` | 不传 |
| `newbee session doctor` | 无额外参数 | — |
| `newbee options content-origins` | 无额外参数 | — |
| `newbee options subscribe-plans` | 无额外参数 | — |
| `newbee options time-ranges` | 无额外参数 | — |
| `newbee plugin list` | `--keyword` | "" |
| `newbee plugin list` | `--page` | 1 |
| `newbee plugin list` | `--page-size` | 50 |
| `newbee plugin get` | `--id` | 必填 |
| `newbee plugin categories` | 无额外参数 | — |
| `newbee plugin game-versions` | 无额外参数 | — |
| `newbee plugin versions` | `--id` | 必填 |
| `newbee plugin versions` | `--page` | 1 |
| `newbee plugin versions` | `--page-size` | 50 |
| `newbee plugin changelog list` | `--id` | 必填 |
| `newbee plugin changelog list` | `--page` | 1 |
| `newbee plugin changelog list` | `--page-size` | 50 |
| `newbee plugin changelog get` | `--id` | 必填 |
| `newbee plugin co-author search` | `--keyword` | 必填 |
| `newbee plugin co-author list` | `--id` | 必填 |
| `newbee plugin reference search` | `--keyword` | 必填 |
| `newbee plugin reference list` | `--id` | 必填 |
| `newbee config list` | `--keyword` | "" |
| `newbee config list` | `--offset` | 0 |
| `newbee config list` | `--page-size` | 50 |
| `newbee config get` | `--id` | 必填 |
| `newbee config backups` | 无额外参数 | — |
| `newbee config backup-get` | `--id` | 必填 |
| `newbee config co-author search` | `--keyword` | 必填 |
| `newbee config co-author list` | `--id` | 必填 |
| `newbee config reference search` | `--keyword` | 必填 |
| `newbee config reference list` | `--id` | 必填 |
| `newbee wa list` | `--keyword` | "" |
| `newbee wa list` | `--offset` | 0 |
| `newbee wa list` | `--page-size` | 50 |
| `newbee wa get` | `--id` | 必填 |
| `newbee wa categories` | `--game-version-id` | 必填 |
| `newbee wa attachment-paths` | 无额外参数 | — |
| `newbee wa changelog latest` | `--id` | 必填 |
| `newbee wa changelog list` | `--id` | 必填 |
| `newbee wa changelog list` | `--page` | 1 |
| `newbee wa changelog list` | `--page-size` | 50 |
| `newbee wa co-author search` | `--keyword` | 必填 |
| `newbee wa co-author list` | `--id` | 必填 |
| `newbee wa reference search` | `--keyword` | 必填 |
| `newbee wa reference list` | `--id` | 必填 |

<a id="newbee-backup-create"></a>
### `backup create`

Schema：`fupload.v1.newbee.backup.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_dir` | `string` | 否/条件必填 | 拒绝 | 非空 | local source directory (no HTTP field)；selective ZIP/font upload -> /v3/share/create -> optional /share/update；generate is local only; create accepts generation inputs or an existing bundle; upload verifies bundle layout/hash before any remote request |
| `game_version_id` | `integer` | 否/条件必填 | 拒绝 | 最小 1 | versionid；selective ZIP/font upload -> /v3/share/create -> optional /share/update；Positive live metadata game_version parent ID -> manifest versionid; differs from plugin game_version_list build strings. |
| `output_dir` | `string` | 否/条件必填 | 拒绝 | 非空 | local bundle directory (no HTTP field)；selective ZIP/font upload -> /v3/share/create -> optional /share/update；generate is local only; create accepts generation inputs or an existing bundle; upload verifies bundle layout/hash before any remote request |
| `known_plugins` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | knowplug_list；selective ZIP/font upload -> /v3/share/create -> optional /share/update；Known addons are references without ZIP. Require name,id,fileName,fileUrl,mod_file_id,mod_version,display_name,updateType; scan does not synthesize this metadata. |
| `unknown_plugins` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknown_plug + t_unKnown_list；selective ZIP/font upload -> /v3/share/create -> optional /share/update；Selected AddOns folders only; signed ZIP type unknown_plug; ZIP top-level names must exactly match t_unKnown_list. |
| `materials` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | material + t_material_list；selective ZIP/font upload -> /v3/share/create -> optional /share/update；Selected Interface material paths only; AddOns is forbidden here; signed ZIP type material; ZIP roots match t_material_list. |
| `fonts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | font_hash + t_font_list；selective ZIP/font upload -> /v3/share/create -> optional /share/update；Selected .ttf copies only. Native OssUploader.uploadFolder uploads the staged folder, returns font_hash; official signed client + Node are dependencies. Nonempty font upload not live-tested. |
| `wtf_accounts` | `array` | 否/条件必填 | 拒绝 | [{account,include_common,roles:[{server,name}]}]; exact role choices | wtf[].account/server[].serverName/roleList[].name/commonConfig/roleList[].zip；selective ZIP/font upload -> /v3/share/create -> optional /share/update；Each account has account/include_common/roles[{server,name}]. common is root files+SavedVariables only; role ZIP must contain only that role root. Unselected accounts/roles and *.bak are excluded. No caller-provided archive URL. |
| `bundle_file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | local backup-bundle.json (no HTTP field)；selective ZIP/font upload -> /v3/share/create -> optional /share/update；generate is local only; create accepts generation inputs or an existing bundle; upload verifies bundle layout/hash before any remote request |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 200 | t_name；selective ZIP/font upload -> /v3/share/create -> optional /share/update；Initial create name is server-chosen; requested name is a separate /share/update {t_id,t_name} write followed by readback. |

字段映射依据：`fupload/scripts/fupload_cli/newbee_backup.py:generate_backup/upload_backup/rename_backup/delete_backups; D:/Software/NewBeeBox/resources/app.asar!js/8761.js; !js/app.js module29474`。

<a id="newbee-backup-delete"></a>
### `backup delete`

Schema：`fupload.v1.newbee.backup.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_ids` | `array` | 是 | 拒绝 | 非空；最多项 1000 | t_id (one POST per selected ID)；/v3/share/delete；Explicit positive IDs only. Complete author configuration pagination/detail association lookup; any reference/unknown relationship blocks deletion; recheck before each one-shot delete, then negative list readback. |
| `confirm_delete` | `boolean` | 是 | 拒绝 | 可选 `[true]` | local deletion confirmation (no HTTP field)；/v3/share/delete；Literal true is local consent only, never bypasses reference guard. |

字段映射依据：`fupload/scripts/fupload_cli/newbee_backup.py:generate_backup/upload_backup/rename_backup/delete_backups; D:/Software/NewBeeBox/resources/app.asar!js/8761.js; !js/app.js module29474`。

<a id="newbee-backup-generate"></a>
### `backup generate`

Schema：`fupload.v1.newbee.backup.generate`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_dir` | `string` | 是 | 拒绝 | 非空 | local source directory (no HTTP field)；local generation；generate is local only; create accepts generation inputs or an existing bundle; upload verifies bundle layout/hash before any remote request |
| `game_version_id` | `integer` | 是 | 拒绝 | 最小 1 | versionid；local generation；Positive live metadata game_version parent ID -> manifest versionid; differs from plugin game_version_list build strings. |
| `output_dir` | `string` | 是 | 拒绝 | 非空 | local bundle directory (no HTTP field)；local generation；generate is local only; create accepts generation inputs or an existing bundle; upload verifies bundle layout/hash before any remote request |
| `known_plugins` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | knowplug_list；local generation；Known addons are references without ZIP. Require name,id,fileName,fileUrl,mod_file_id,mod_version,display_name,updateType; scan does not synthesize this metadata. |
| `unknown_plugins` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknown_plug + t_unKnown_list；local generation；Selected AddOns folders only; signed ZIP type unknown_plug; ZIP top-level names must exactly match t_unKnown_list. |
| `materials` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | material + t_material_list；local generation；Selected Interface material paths only; AddOns is forbidden here; signed ZIP type material; ZIP roots match t_material_list. |
| `fonts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | font_hash + t_font_list；local generation；Selected .ttf copies only. Native OssUploader.uploadFolder uploads the staged folder, returns font_hash; official signed client + Node are dependencies. Nonempty font upload not live-tested. |
| `wtf_accounts` | `array` | 否/条件必填 | 拒绝 | [{account,include_common,roles:[{server,name}]}]; exact role choices | wtf[].account/server[].serverName/roleList[].name/commonConfig/roleList[].zip；local generation；Each account has account/include_common/roles[{server,name}]. common is root files+SavedVariables only; role ZIP must contain only that role root. Unselected accounts/roles and *.bak are excluded. No caller-provided archive URL. |

字段映射依据：`fupload/scripts/fupload_cli/newbee_backup.py:generate_backup/upload_backup/rename_backup/delete_backups; D:/Software/NewBeeBox/resources/app.asar!js/8761.js; !js/app.js module29474`。

<a id="newbee-backup-rename"></a>
### `backup rename`

Schema：`fupload.v1.newbee.backup.rename`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 最小 1 | t_id；/share/update；generate is local only; create accepts generation inputs or an existing bundle; upload verifies bundle layout/hash before any remote request |
| `name` | `string` | 是 | 拒绝 | 非空；最多字符 200 | t_name；/share/update；Initial create name is server-chosen; requested name is a separate /share/update {t_id,t_name} write followed by readback. |

字段映射依据：`fupload/scripts/fupload_cli/newbee_backup.py:generate_backup/upload_backup/rename_backup/delete_backups; D:/Software/NewBeeBox/resources/app.asar!js/8761.js; !js/app.js module29474`。

<a id="newbee-backup-upload"></a>
### `backup upload`

Schema：`fupload.v1.newbee.backup.upload`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `bundle_file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | local backup-bundle.json (no HTTP field)；selective ZIP/font upload -> /v3/share/create -> optional /share/update；generate is local only; create accepts generation inputs or an existing bundle; upload verifies bundle layout/hash before any remote request |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 200 | t_name；selective ZIP/font upload -> /v3/share/create -> optional /share/update；Initial create name is server-chosen; requested name is a separate /share/update {t_id,t_name} write followed by readback. |

字段映射依据：`fupload/scripts/fupload_cli/newbee_backup.py:generate_backup/upload_backup/rename_backup/delete_backups; D:/Software/NewBeeBox/resources/app.asar!js/8761.js; !js/app.js module29474`。

<a id="newbee-config-create"></a>
### `config create`

Schema：`fupload.v1.newbee.config.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `title` | `string` | 是 | 拒绝 | 非空 | title；POST JSON /creator/wow/share_config/release；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `content` | `string` | 是 | 拒绝 | 非空 | content；POST JSON /creator/wow/share_config/release；Public configuration-share description body (HTML/Markdown), NOT raw WTF/backup content. Preserve full text on get; cloud_id/linked_mods/ignored arrays/roleid separately select configuration data. |
| `content_format` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_format；POST JSON /creator/wow/share_config/release；1=HTML/rich text, 2=Markdown; no raw WTF serialization is sent in this field |
| `intro` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | intro；POST JSON /creator/wow/share_config/release；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `picture_urls` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pic_url；POST JSON /creator/wow/share_config/release；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `picture_files` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pic_url；local file -> media multipart -> pic_url in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `content_origin` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_origin；POST JSON /creator/wow/share_config/release；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `public` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | sharing；POST JSON /creator/wow/share_config/release；public -> sharing=1; private -> sharing=0; private forces link_to_channel=false |
| `submit_for_review` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | local control (not sent)；preflight；submit_for_review=true is required for requested public publication; no separate review wire flag |
| `link_to_channel` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | link_to_channel；POST JSON /creator/wow/share_config/release；private forces false; plugin create always false; other writes use caller/current value only when public |
| `subscribe_plan_level` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | subscribe_plan_level；POST JSON /creator/wow/share_config/release；Live selectable subscription-plan level; 0=none. No implicit client payment-method label is transmitted. |
| `price` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | price；POST JSON /creator/wow/share_config/release；Python price is integer fen. price=0 normalizes time_range to empty string. Nonzero values/options are selected through live options endpoints; do not copy NCC yuan units. |
| `time_range` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | time_range；POST JSON /creator/wow/share_config/release；Python price is integer fen. price=0 normalizes time_range to empty string. Nonzero values/options are selected through live options endpoints; do not copy NCC yuan units. |
| `co_authors` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=4 |
| `references` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=3 |
| `cloud_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | cloud_id；POST JSON /creator/wow/share_config/release；Choose existing backup ID first. Changing it during update requires complete descendant reselection. |
| `linked_mods` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | linked_mods；POST JSON /creator/wow/share_config/release；Only selected mod_ids from the live backup are authoritative; other submitted metadata is canonicalized from the selected backup. update_type is wire updateType; it is not an arbitrary version-edit override. |
| `ignored_unknown_mods` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | ignored_unknown_mods；POST JSON /creator/wow/share_config/release；These are exclusion-name arrays, not inclusion arrays. Every name must exist in the selected backup; ignored_fronts is the actual historical wire spelling. |
| `ignored_materials` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | ignored_materials；POST JSON /creator/wow/share_config/release；These are exclusion-name arrays, not inclusion arrays. Every name must exist in the selected backup; ignored_fronts is the actual historical wire spelling. |
| `ignored_fronts` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | ignored_fronts；POST JSON /creator/wow/share_config/release；These are exclusion-name arrays, not inclusion arrays. Every name must exist in the selected backup; ignored_fronts is the actual historical wire spelling. |
| `roleid` | `string` | 是 | 拒绝 | 见动作条件及嵌套结构 | roleid；POST JSON /creator/wow/share_config/release；Empty string means no shared role; otherwise must be an available role_id from the chosen cloud backup; do not send local filesystem role names here. Backup get normalizes the returned numeric role_id to a string matching this schema; use that exact live selector. |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:create_config/update_config; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js:1913-1934`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-config-delete"></a>
### `config delete`

Schema：`fupload.v1.newbee.config.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | id；POST JSON /creator/wow/share_config/delete；Single owned-record ID; get before delete, negative author-list readback afterward. NCC has no equivalent main-record delete. |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | local control (not sent)；preflight；literal DELETE; read target before single-record mutation; never a backup reference override |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:delete`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-config-edit"></a>
### `config edit`

Schema：`fupload.v1.newbee.config.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 非空 | tid；POST JSON /creator/wow/share_config/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `title` | `string` | 否/条件必填 | 拒绝 | 非空 | title；POST JSON /creator/wow/share_config/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `content` | `string` | 否/条件必填 | 拒绝 | 非空 | content；POST JSON /creator/wow/share_config/update；Public configuration-share description body (HTML/Markdown), NOT raw WTF/backup content. Preserve full text on get; cloud_id/linked_mods/ignored arrays/roleid separately select configuration data. |
| `content_format` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | content_format；POST JSON /creator/wow/share_config/update；1=HTML/rich text, 2=Markdown; no raw WTF serialization is sent in this field |
| `intro` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | intro；POST JSON /creator/wow/share_config/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `picture_urls` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pic_url；POST JSON /creator/wow/share_config/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `picture_files` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pic_url；local file -> media multipart -> pic_url in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `content_origin` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | content_origin；POST JSON /creator/wow/share_config/update；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `public` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | sharing；POST JSON /creator/wow/share_config/update；public -> sharing=1; private -> sharing=0; private forces link_to_channel=false |
| `submit_for_review` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | local control (not sent)；preflight；submit_for_review=true is required for requested public publication; no separate review wire flag |
| `link_to_channel` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | link_to_channel；POST JSON /creator/wow/share_config/update；private forces false; plugin create always false; other writes use caller/current value only when public |
| `subscribe_plan_level` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | subscribe_plan_level；POST JSON /creator/wow/share_config/update；Live selectable subscription-plan level; 0=none. No implicit client payment-method label is transmitted. |
| `price` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | price；POST JSON /creator/wow/share_config/update；Python price is integer fen. price=0 normalizes time_range to empty string. Nonzero values/options are selected through live options endpoints; do not copy NCC yuan units. |
| `time_range` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | time_range；POST JSON /creator/wow/share_config/update；Python price is integer fen. price=0 normalizes time_range to empty string. Nonzero values/options are selected through live options endpoints; do not copy NCC yuan units. |
| `co_authors` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=4 |
| `references` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=3 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:create_config/update_config; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js:1913-1934`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-config-update"></a>
### `config update`

Schema：`fupload.v1.newbee.config.update`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 非空 | tid；POST JSON /creator/wow/share_config/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `cloud_id` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | cloud_id；POST JSON /creator/wow/share_config/update；Choose existing backup ID first. Changing it during update requires complete descendant reselection. |
| `linked_mods` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | linked_mods；POST JSON /creator/wow/share_config/update；Only selected mod_ids from the live backup are authoritative; other submitted metadata is canonicalized from the selected backup. update_type is wire updateType; it is not an arbitrary version-edit override. |
| `ignored_unknown_mods` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | ignored_unknown_mods；POST JSON /creator/wow/share_config/update；These are exclusion-name arrays, not inclusion arrays. Every name must exist in the selected backup; ignored_fronts is the actual historical wire spelling. |
| `ignored_materials` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | ignored_materials；POST JSON /creator/wow/share_config/update；These are exclusion-name arrays, not inclusion arrays. Every name must exist in the selected backup; ignored_fronts is the actual historical wire spelling. |
| `ignored_fronts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | ignored_fronts；POST JSON /creator/wow/share_config/update；These are exclusion-name arrays, not inclusion arrays. Every name must exist in the selected backup; ignored_fronts is the actual historical wire spelling. |
| `roleid` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | roleid；POST JSON /creator/wow/share_config/update；Empty string means no shared role; otherwise must be an available role_id from the chosen cloud backup; do not send local filesystem role names here. Backup get normalizes the returned numeric role_id to a string matching this schema; use that exact live selector. |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:create_config/update_config; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js:1913-1934`。

<a id="newbee-config-co-author-set"></a>
### `config-co-author set`

Schema：`fupload.v1.newbee.config-co-author.set`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `content_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_id；POST /creator/co_author/set；Positive source/content ID in the resource-specific numeric namespace; separate relationship mutation |
| `co_authors` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=4 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:execute_write/_replace_relationships`。

<a id="newbee-config-reference-set"></a>
### `config-reference set`

Schema：`fupload.v1.newbee.config-reference.set`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `source_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | source_id；POST /creator/content_reference/set；Positive source/content ID in the resource-specific numeric namespace; separate relationship mutation |
| `references` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=3 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:execute_write/_replace_relationships`。

<a id="newbee-plugin-create"></a>
### `plugin create`

Schema：`fupload.v1.newbee.plugin.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `name` | `string` | 是 | 拒绝 | 非空 | name；POST JSON /creator/wow/mod/create；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `mod_categories` | `array` | 是 | 拒绝 | 非空；最多项 5 | mod_categories；POST JSON /creator/wow/mod/create；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `content_origin` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_origin；POST JSON /creator/wow/mod/create；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `content_format` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_format；POST JSON /creator/wow/mod/create；1=HTML/rich text, 2=Markdown; no raw WTF serialization is sent in this field |
| `intro` | `string` | 是 | 拒绝 | 见动作条件及嵌套结构 | intro；POST JSON /creator/wow/mod/create；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `description` | `string` | 是 | 拒绝 | 见动作条件及嵌套结构 | description；POST JSON /creator/wow/mod/create；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `logo` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | logo；POST JSON /creator/wow/mod/create；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `logo_file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | logo；local file -> media multipart -> logo in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `screenshots` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | screenshots；POST JSON /creator/wow/mod/create；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `screenshot_files` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | screenshots；local file -> media multipart -> screenshots in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `public` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | share_state；POST JSON /creator/wow/mod/create；create is always share_state=0/private even when public=true; public request is deferred until a separate first-version upload and edit to share_state=1 |
| `submit_for_review` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | local control (not sent)；preflight；submit_for_review=true is required for requested public publication; no separate review wire flag |
| `subscribe_plan_level` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | subscribe_plan_level；POST JSON /creator/wow/mod/create；Live selectable subscription-plan level; 0=none. No implicit client payment-method label is transmitted. |
| `link_to_channel` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | link_to_channel；POST JSON /creator/wow/mod/create；private forces false; plugin create always false; other writes use caller/current value only when public |
| `co_authors` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=1 |
| `references` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=1 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:create_plugin/edit_plugin; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3PluginForm-DlHiNxtf.js:718-781`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-plugin-delete"></a>
### `plugin delete`

Schema：`fupload.v1.newbee.plugin.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | id；POST JSON /creator/wow/mod/remove；Single owned-record ID; get before delete, negative author-list readback afterward. NCC has no equivalent main-record delete. |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | local control (not sent)；preflight；literal DELETE; read target before single-record mutation; never a backup reference override |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:delete`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-plugin-edit"></a>
### `plugin edit`

Schema：`fupload.v1.newbee.plugin.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 非空 | id；POST JSON /creator/wow/mod/edit；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空 | name；POST JSON /creator/wow/mod/edit；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `mod_categories` | `array` | 否/条件必填 | 拒绝 | 非空；最多项 5 | mod_categories；POST JSON /creator/wow/mod/edit；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `content_origin` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | content_origin；POST JSON /creator/wow/mod/edit；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `content_format` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | content_format；POST JSON /creator/wow/mod/edit；1=HTML/rich text, 2=Markdown; no raw WTF serialization is sent in this field |
| `intro` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | intro；POST JSON /creator/wow/mod/edit；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `description` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | description；POST JSON /creator/wow/mod/edit；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `logo` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | logo；POST JSON /creator/wow/mod/edit；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `logo_file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | logo；local file -> media multipart -> logo in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `screenshots` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | screenshots；POST JSON /creator/wow/mod/edit；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `screenshot_files` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | screenshots；local file -> media multipart -> screenshots in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `public` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | share_state；POST JSON /creator/wow/mod/edit；create is always share_state=0/private even when public=true; public request is deferred until a separate first-version upload and edit to share_state=1 |
| `submit_for_review` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | local control (not sent)；preflight；submit_for_review=true is required for requested public publication; no separate review wire flag |
| `subscribe_plan_level` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | subscribe_plan_level；POST JSON /creator/wow/mod/edit；Live selectable subscription-plan level; 0=none. No implicit client payment-method label is transmitted. |
| `link_to_channel` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | link_to_channel；POST JSON /creator/wow/mod/edit；private forces false; plugin create always false; other writes use caller/current value only when public |
| `co_authors` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=1 |
| `references` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=1 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:create_plugin/edit_plugin; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3PluginForm-DlHiNxtf.js:718-781`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-plugin-update"></a>
### `plugin update`

Schema：`fupload.v1.newbee.plugin.update`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `mod_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | mod_id；multipart /creator/wow/mod_file/upload_mod_file；New immutable version; read current versions and reject duplicate version before upload |
| `version` | `string` | 是 | 拒绝 | 非空 | version；multipart /creator/wow/mod_file/upload_mod_file；New immutable version; read current versions and reject duplicate version before upload |
| `game_version_list` | `array` | 是 | 拒绝 | 非空 | game_version_list；multipart /creator/wow/mod_file/upload_mod_file；JSON array encoded as multipart text; each value is a live nested client build string, never the parent game-version ID. |
| `file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | multipart file；multipart /creator/wow/mod_file/upload_mod_file；Python/Creator snapshot accepts .zip/.rar/.7z <=300 MiB. Current official NCC pack/push ZIP limit is 2048 MiB and is a separate execution channel. |
| `changelog` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | changelog；multipart /creator/wow/mod_file/upload_mod_file；New immutable version; read current versions and reject duplicate version before upload |
| `link_to_channel` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | link_to_channel；multipart /creator/wow/mod_file/upload_mod_file；JSON boolean multipart text; omitted update field preserves current remote link-to-channel state. |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:update_plugin; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step4PluginUpload-ut4XYEw2.js`。

<a id="newbee-plugin-changelog-edit"></a>
### `plugin-changelog edit`

Schema：`fupload.v1.newbee.plugin-changelog.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `file_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | file_id；POST /creator/wow/mod_file/edit_changelog；file_id selects one historical plugin file; empty/null changelog clears where schema allows |
| `changelog` | `string` | 是 | 允许 | 见动作条件及嵌套结构 | changelog；POST /creator/wow/mod_file/edit_changelog；file_id selects one historical plugin file; empty/null changelog clears where schema allows |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:execute_write`。

<a id="newbee-plugin-co-author-set"></a>
### `plugin-co-author set`

Schema：`fupload.v1.newbee.plugin-co-author.set`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `content_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_id；POST /creator/co_author/set；Positive source/content ID in the resource-specific numeric namespace; separate relationship mutation |
| `co_authors` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=1 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:execute_write/_replace_relationships`。

<a id="newbee-plugin-reference-set"></a>
### `plugin-reference set`

Schema：`fupload.v1.newbee.plugin-reference.set`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `source_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | source_id；POST /creator/content_reference/set；Positive source/content ID in the resource-specific numeric namespace; separate relationship mutation |
| `references` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=1 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:execute_write/_replace_relationships`。

<a id="newbee-wa-create"></a>
### `wa create`

Schema：`fupload.v1.newbee.wa.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_version_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | game_version_id；POST JSON /creator/wow/wa/publish；Live parent game-version ID; WA edit carries this field but cross-version edit acceptance was not live-tested; categories must be valid for final version. |
| `name` | `string` | 是 | 拒绝 | 非空 | name；POST JSON /creator/wow/wa/publish；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `intro` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | intro；POST JSON /creator/wow/wa/publish；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `description` | `string` | 是 | 拒绝 | 非空 | description；POST JSON /creator/wow/wa/publish；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `content_format` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_format；POST JSON /creator/wow/wa/publish；1=HTML/rich text, 2=Markdown; no raw WTF serialization is sent in this field |
| `thumbnail` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | thumbnail；POST JSON /creator/wow/wa/publish；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `thumbnail_file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | thumbnail；local file -> media multipart -> thumbnail in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `images` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | images；POST JSON /creator/wow/wa/publish；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `image_files` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | images；local file -> media multipart -> images in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `category_id_list` | `array` | 是 | 拒绝 | 非空；最多项 5 | category_id_list；POST JSON /creator/wow/wa/publish；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `content_origin` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_origin；POST JSON /creator/wow/wa/publish；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `subscribe_plan_level` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | subscribe_plan_level；POST JSON /creator/wow/wa/publish；Live selectable subscription-plan level; 0=none. No implicit client payment-method label is transmitted. |
| `price` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | price；POST JSON /creator/wow/wa/publish；Python price is integer fen. price=0 normalizes time_range to empty string. Nonzero values/options are selected through live options endpoints; do not copy NCC yuan units. |
| `time_range` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | time_range；POST JSON /creator/wow/wa/publish；Python price is integer fen. price=0 normalizes time_range to empty string. Nonzero values/options are selected through live options endpoints; do not copy NCC yuan units. |
| `public` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | share_state；POST JSON /creator/wow/wa/publish；public -> share_state=1; private -> share_state=2; private forces link_to_channel=false |
| `submit_for_review` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | local control (not sent)；preflight；submit_for_review=true is required for requested public publication; no separate review wire flag |
| `link_to_channel` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | link_to_channel；POST JSON /creator/wow/wa/publish；private forces false; plugin create always false; other writes use caller/current value only when public |
| `attachments` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | attachments；POST JSON /creator/wow/wa/publish；Objects are name/install_type/install_path/value/is_compressed/timestamp; install type/path from live options; value is uploadserver index code, not local path or arbitrary signed URL. |
| `co_authors` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=3 |
| `references` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=2 |
| `wa_str` | `string` | 是 | 拒绝 | 非空 | wa_str；POST JSON /creator/wow/wa/publish；Content is sensitive exported WA/string material, loaded via @file. Collection mode uses official JSON-array string representation plus ordered wa_str_titles; do not emit raw content. |
| `wa_str_titles` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | wa_str_titles；POST JSON /creator/wow/wa/publish；Ordered titles follow collection string order; on update omission preserves the current remote titles. |
| `wa_log` | `string` | 是 | 拒绝 | 非空 | wa_log；POST JSON /creator/wow/wa/publish；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `string_mode` | `string` | 是 | 拒绝 | 可选 `["single", "collection"]` | string_mode；POST JSON /creator/wow/wa/publish；single or collection; collection requires ordered titles; this is Python/Creator support, official NCC publish supports single only. |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:create_wa/edit_wa/update_wa; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3StringForm-Bx7R9KLT.js:875-932`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-wa-delete"></a>
### `wa delete`

Schema：`fupload.v1.newbee.wa.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | id；POST JSON /creator/wow/wa/delete；Single owned-record ID; get before delete, negative author-list readback afterward. NCC has no equivalent main-record delete. |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | local control (not sent)；preflight；literal DELETE; read target before single-record mutation; never a backup reference override |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:delete`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-wa-edit"></a>
### `wa edit`

Schema：`fupload.v1.newbee.wa.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 非空 | id；POST JSON /creator/wow/wa/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `game_version_id` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | game_version_id；POST JSON /creator/wow/wa/update；Live parent game-version ID; WA edit carries this field but cross-version edit acceptance was not live-tested; categories must be valid for final version. |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空 | name；POST JSON /creator/wow/wa/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `intro` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | intro；POST JSON /creator/wow/wa/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `description` | `string` | 否/条件必填 | 拒绝 | 非空 | description；POST JSON /creator/wow/wa/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `content_format` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | content_format；POST JSON /creator/wow/wa/update；1=HTML/rich text, 2=Markdown; no raw WTF serialization is sent in this field |
| `thumbnail` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | thumbnail；POST JSON /creator/wow/wa/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `thumbnail_file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | thumbnail；local file -> media multipart -> thumbnail in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `images` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | images；POST JSON /creator/wow/wa/update；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `image_files` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | images；local file -> media multipart -> images in main form；Local uploads resolve to URLs. File lists append to retained/current URL lists; remote URL-list field explicitly replaces its list. |
| `category_id_list` | `array` | 否/条件必填 | 拒绝 | 非空；最多项 5 | category_id_list；POST JSON /creator/wow/wa/update；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `content_origin` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | content_origin；POST JSON /creator/wow/wa/update；Read live origin/categories first; categories are IDs, not labels; category list <=5. |
| `subscribe_plan_level` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | subscribe_plan_level；POST JSON /creator/wow/wa/update；Live selectable subscription-plan level; 0=none. No implicit client payment-method label is transmitted. |
| `price` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | price；POST JSON /creator/wow/wa/update；Python price is integer fen. price=0 normalizes time_range to empty string. Nonzero values/options are selected through live options endpoints; do not copy NCC yuan units. |
| `time_range` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | time_range；POST JSON /creator/wow/wa/update；Python price is integer fen. price=0 normalizes time_range to empty string. Nonzero values/options are selected through live options endpoints; do not copy NCC yuan units. |
| `public` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | share_state；POST JSON /creator/wow/wa/update；public -> share_state=1; private -> share_state=2; private forces link_to_channel=false |
| `submit_for_review` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | local control (not sent)；preflight；submit_for_review=true is required for requested public publication; no separate review wire flag |
| `link_to_channel` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | link_to_channel；POST JSON /creator/wow/wa/update；private forces false; plugin create always false; other writes use caller/current value only when public |
| `attachments` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | attachments；POST JSON /creator/wow/wa/update；Objects are name/install_type/install_path/value/is_compressed/timestamp; install type/path from live options; value is uploadserver index code, not local path or arbitrary signed URL. |
| `co_authors` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=3 |
| `references` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=2 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:create_wa/edit_wa/update_wa; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3StringForm-Bx7R9KLT.js:875-932`；`fupload/scripts/fupload_cli/newbee.py:execute_write and schema validators`。

<a id="newbee-wa-update"></a>
### `wa update`

Schema：`fupload.v1.newbee.wa.update`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | id；POST JSON /creator/wow/wa/update_wa_str；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `version` | `string` | 否/条件必填 | 拒绝 | 非空 | version；POST JSON /creator/wow/wa/update_wa_str；WA next version is fetched when omitted; explicit/derived version must exceed remote current version; this is not plugin free-text version semantics. |
| `wa_str` | `string` | 是 | 拒绝 | 非空 | wa_str；POST JSON /creator/wow/wa/update_wa_str；Content is sensitive exported WA/string material, loaded via @file. Collection mode uses official JSON-array string representation plus ordered wa_str_titles; do not emit raw content. |
| `wa_str_titles` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | wa_str_titles；POST JSON /creator/wow/wa/update_wa_str；Ordered titles follow collection string order; on update omission preserves the current remote titles. |
| `wa_log` | `string` | 是 | 拒绝 | 非空 | wa_log；POST JSON /creator/wow/wa/update_wa_str；create sends explicit form; edit/update reads current detail and preserves omitted editable form fields |
| `link_to_channel` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | link_to_channel；POST JSON /creator/wow/wa/update_wa_str；private forces false; plugin create always false; other writes use caller/current value only when public |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:create_wa/edit_wa/update_wa; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3StringForm-Bx7R9KLT.js:875-932`。

<a id="newbee-wa-changelog-edit"></a>
### `wa-changelog edit`

Schema：`fupload.v1.newbee.wa-changelog.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | wa_log_id；POST /creator/wow/wa_log/edit；Edit one changelog; optional wa_id is only for immediate readback, not a mutation field |
| `wa_id` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | wa_id (readback only)；readback /creator/wow/wa_log/list；Edit one changelog; optional wa_id is only for immediate readback, not a mutation field |
| `wa_log` | `string` | 是 | 允许 | 见动作条件及嵌套结构 | content；POST /creator/wow/wa_log/edit；Edit one changelog; optional wa_id is only for immediate readback, not a mutation field |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:execute_write`。

<a id="newbee-wa-co-author-set"></a>
### `wa-co-author set`

Schema：`fupload.v1.newbee.wa-co-author.set`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `content_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | content_id；POST /creator/co_author/set；Positive source/content ID in the resource-specific numeric namespace; separate relationship mutation |
| `co_authors` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | co_authors；separate relationship POST /creator/co_author/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. user_id + share_percent (fraction, total <=1); content_type=3 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:execute_write/_replace_relationships`。

<a id="newbee-wa-media-upload"></a>
### `wa-media upload`

Schema：`fupload.v1.newbee.wa-media.upload`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | local file -> upload index/URL；kind=image: /creator/wow/wa/upload_media; kind=attachment: uploadserver /upload/v3/prepare -> object PUT -> /upload/v3/index/get；Attachment uploader uses indexType=2 and checksumAlgorithm=1; install_type/path are returned descriptor fields, not object PUT credentials |
| `kind` | `string` | 是 | 拒绝 | 可选 `["image", "attachment"]` | local branch selector；kind=image: /creator/wow/wa/upload_media; kind=attachment: uploadserver /upload/v3/prepare -> object PUT -> /upload/v3/index/get；Attachment uploader uses indexType=2 and checksumAlgorithm=1; install_type/path are returned descriptor fields, not object PUT credentials |
| `install_type` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | attachment.install_type (local returned object)；kind=image: /creator/wow/wa/upload_media; kind=attachment: uploadserver /upload/v3/prepare -> object PUT -> /upload/v3/index/get；Attachment uploader uses indexType=2 and checksumAlgorithm=1; install_type/path are returned descriptor fields, not object PUT credentials |
| `install_path` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | attachment.install_path (local returned object)；kind=image: /creator/wow/wa/upload_media; kind=attachment: uploadserver /upload/v3/prepare -> object PUT -> /upload/v3/index/get；Attachment uploader uses indexType=2 and checksumAlgorithm=1; install_type/path are returned descriptor fields, not object PUT credentials |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:upload_attachment/execute_write`。

<a id="newbee-wa-reference-set"></a>
### `wa-reference set`

Schema：`fupload.v1.newbee.wa-reference.set`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `source_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | source_id；POST /creator/content_reference/set；Positive source/content ID in the resource-specific numeric namespace; separate relationship mutation |
| `references` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | references；separate relationship POST /creator/content_reference/set；Presence replaces the complete relation; [] clears. Omission preserves. Main write/readback happens before this side effect. items {type,id}; source_type=2 |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:_replace_relationships; D:/Code/Fuploader/analyze/legacy-newbee/creator/assets/Step3ShareConfigForm-1CKiEeDd.js submit content_type=4/source_type=3/share_percent ratio/100`；`fupload/scripts/fupload_cli/newbee.py:execute_write/_replace_relationships`。

<a id="newbee-wa-share-code-set"></a>
### `wa-share-code set`

Schema：`fupload.v1.newbee.wa-share-code.set`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `module_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | moduleId；POST next-origin /bannerserver/ShareCode/Set；gameId=1,moduleType=3 fixed; module_id is a WA record ID; no caller credential/base URL |

字段映射依据：`fupload/scripts/fupload_cli/newbee.py:execute_write`。

<a id="dd"></a>
## 网易 DD

### 来源与验证范围

核对 DD 100130 的官方 Python 资源包、作者网页表单及 Fupload 最终请求构建器。字段映射记录在相邻 `dd.json`，主要证据为 `dd.py` 的 `plugin_form`、`config_form`、`wa_form`、`normalize_commercial`，以及 `dd_backup.py`。`test_dd_wire_matrix.py` 对插件、配置、WA 的最终表单逐字段核对；这类本地请求测试不等于所有字段都已远程发布。

已在本机验证：普通权限借用正在运行客户端的 Cookie，作者查询和合成 ZIP 上传正常；当前六个动态游戏分支（10001、2、7、3、6、4）均完成合成备份生成、上传、改名、预览、删除及读回，测试记录已清理、原有五条备份保留。另以私密测试配置验证关联备份即使 confirm_delete=true 也拒删，并完成 2823 字符 HTML 修改与读回；随后按配置、备份顺序清理。另一邮箱账号、全部付费/频道组合、长期切号场景未做实机发布验证。

### 登录和能力边界

- `dd session doctor` 只诊断；`dd session start` 返回一个不透明任务 `session_id`，业务命令统一带 `--session`。在 `finally` 调用 `dd session stop --session <id>`；不要为每个对象创建一次会话。
- GUI 正在运行：借用其已存在的网页会话，`session_source=desktop-cookie`、`native_login_count=0`；失败就停止，不再创建另一条桌面登录，不关闭客户端。旧 `--confirm-close-gui` 参数仅兼容调用。
- GUI 未运行：读取官方自动登录凭据。邮箱是 `urs + urs_token + normal`；手机号是 `mobile + urs_mobile_token + normal|mobile_password|mobile_uplink`。只有 `mobile_password` 令 `isPassword=true`；未知组合拒绝。
- 借用会话的原始登录方式无需再次判断；停止仅清理自己的 HTTP/runtime，不请求账号退出。
- CC 频道列表依赖当前 GUI 的 CC JWT，作者 Cookie 不能直接替代。新增 `dd_channel.py` 仅对该可选操作只读当前 GUI 内存，固定匹配 DD 100130/CPython 3.7.17 的签名、文件哈希及运行时布局，核对同用户、进程创建时间与会话锚点；JWT 不落盘、不输出。高权限 DD 需要同用户管理员终端查询频道；启用频道关联写入时，也需以相同权限启动 Fupload 任务会话。普通作者上传仍只借 Cookie，不要求管理员。缓存 JWT 缺失、失效或读取失败直接停止，不重新登录 DD。11 项产品 mock 测试及 6 项独立 Qt 夹具验证通过；当前 GUI 的管理员实机读取待用户回传结果。

### 商业与可见性条件

`scope` 使用 `public|private`；它不等于免费/付费。`need_buy=true` 必须同时提供 `price_fen` 和 `buy_life_type`。`price_fen` 单位为分，只允许 0 或 10 至 20000。已有对象的外层免费/付费模式锁定；不能通过 edit 改变 `need_buy || need_anchor_vip` 的整体真假状态。

private 强制不做频道同步、不要求主播 VIP；public 插件和 WA 的 `share_code_life_type` 规范为 `forever`，public 配置不发送该字段。private 创建通常要求分享码期限，付费私密配置有单独例外。配置的 `need_buy` 最终为整数 0/1，其他资源不据此猜类型。

`jump_room=true` 要求 `room_id`；`channel_id` 与 `channel_type` 同时为空或同时有值。`sync_room=true` 要求公开、跳转房间及有效频道。关闭 `jump_room` 会清空房间、频道并关闭同步。`with_associate=false` 清空关联；true 要求非空 `associated_acts`。`need_anchor_vip=true` 要求 `vip_levels`。

`associated_acts` 每项仅 `{sn:string, act_type:"addon"|"share"|"wa"}`。VIP 等级和分类用当前动态候选 ID，不传名称/显示对象。`creation_statement` 必须是用户实际声明。

### 插件与版本

`plugin create` 需要游戏分支、当前 build 字符串、标题、简介、分类、版本类型、版本、详情正文、更新说明、Logo、至少一张详情图及 ZIP。字段表的静态可省略不代表可省掉 Logo/媒体/包：URL 与本地文件提供的是同一需求的两条入口。

`plugin update` 是新版本；`game_type` 和初次发布信息不因此开放修改。重复版本在上传前拒绝。`plugin edit` 只接受当前 Schema 列出的商业、关联、简介、Logo、详情和公告字段。公告 `update_desc` 作用于当前插件，不是任意历史版本日志。作者列表与 detail_v2 的最新版本投影可能不同；重建 modify 时优先采用作者列表的版本/包投影，读回按实际字段核对。

本地 Logo/图片先授权上传，再在最终表单放回地址；`logo_file`、`detail_img_files` 不原样发给发布接口。插件 ZIP 最终对应 `detail_url`，路径分隔符必须为 `/`。

### 配置选择与嵌套结构

依赖顺序是 `backup_sn → backup detail → WTF account/server/role → 该账号的 WA`。更换备份或账号会使原有子选择失效。

- `known_addon_ids` 按 `addon_id` 选择完整候选；`unknown_addon_ids` 实际按标量名称、对象 `name`（缺失才按 `id`）选择，不能因字段后缀就假定都是数字 ID。材质按 `name`，字体按返回的字符串或名称选择。
- WA 的 `*_wa_ids` 实际选择 `uid`；已选 WTF 账号必须有对应映射。`known_wa` 保留候选对象，`unknown_wa.id` 替换为该账号的映射 ID。不要混淆 `uid` 与内部 `id`。
- 全部 `*_update_ids` / `*_update_names` 必须为当前选择的子集。它们更新分组的 `inner_version[选择键]`，不是设置 `items[].update`；已有非零版本标记后加一，其余保留，初始为一。
- `wtf_role_ids` 使用 `backup-get` 返回的稳定角色选择器。Fupload 据此重建 `wtf.accounts[].servers[].items`，不接受原始 WTF 对象或配置文本。
- `retail_ui_config` 输入只允许 `edit_mode_selectors:string[]`、`default_edit_mode_selector:string|null`、`cool_down_selectors:string[]`、`enable_dd_setup_wizard:boolean`。选择器用于本地匹配备份；最终 wire 的 `edit_mode[account]`、`cool_down[account]` 是选中原生对象，前者补 `is_default`。最多五套编辑模式，非空时默认项必须包含在选择中；每个 `spec_tag` 最多一套冷却配置。正式服切换备份时必须重新选择，不接受原始导入字符串作为输入。
- `display_img_files` 上传后追加到现有展示图，最终总数最多 8；不是替换全部图片的隐含指令。

### WA 与附件

WA 版本必须为数字字符串。每次提交 `!WA:2!` 都调用官方解析器获得内部 `parse_wa_uid` 和 `parse_wa_id`，包括编辑时保留的原内容；这两个内部字段不是用户输入。非 WA2 不保留旧解析 ID。

`with_file=true` 的首次创建需要 ZIP 和非空 `file_install_path`；update 省略文件可保留已存在的附件。false 按官方表单保留内部路径，不把它解释成远端对象删除。WA 附件上限 50 MiB；图片及其他文件仍要通过当前授权限制。

### 云备份

`generate` 只在本机生成分组 ZIP 和 `backup-bundle.json`；`upload` 读取该包；`create` 可生成后上传或显式复用一个包。选择字段不得混同配置分享字段。

`wtf_accounts` 为 `[{account:string, include_common:boolean, roles:[{server:string,name:string}]}]`；`include_wtf_root` 单独控制 WTF 根文件。不要默认收集全部账号或角色。字体 ZIP 使用 `Fonts/`，WTF ZIP 使用 `WTF/Account/` 层级；上传前核对包 hash、目录和选择元数据。

真实协议为 `/backup/pre_create` 的五类清单、各选中组的签名对象 PUT、`/backup/finish_create`，再读 detail/list。官方仍可能返回 HTTP 对象地址；仅对已验证的官方精确域名升级 TLS，保留签名的 Content-Type 与 ACL。空组读回可为 null；不能因此误判整个备份未创建。

`name` 最多 14 字符，通过 `/backup/modify_name` 改名。删除前读取所有游戏分支的自有配置分享并解析其 `backup_sn`；有引用、缺失明细、总数/分页异常都停止。每项删除前再查一次关联，删除只发一次，并以刷新后的列表确认消失。

### 只读命令与输入参数

| 命令 | 参数 | 默认/必填 |
| --- | --- | --- |
| `dd backup list` | `--session` | 不传 |
| `dd backup get` | `--session` | 不传 |
| `dd backup get` | `--sn/--backup-sn` | 必填 |
| `dd backup scan` | `--game-dir` | 必填 |
| `dd backup delete-preview` | `--session` | 不传 |
| `dd backup delete-preview` | `--backup-ids` | 不传 |
| `dd backup delete-preview` | `--name-contains` | 不传 |
| `dd backup delete-preview` | `--name-equals` | 不传 |
| `dd backup delete-preview` | `--created-before` | 不传 |
| `dd backup delete-preview` | `--created-after` | 不传 |
| `dd session doctor` | 无额外参数 | — |
| `dd session start` | `--confirm-close-gui` | false |
| `dd session status` | `--session` | 不传 |
| `dd session stop` | `--session` | 必填 |
| `dd options game-types` | `--session` | 不传 |
| `dd options channels` | `--session` | 不传 |
| `dd options life-types` | `--session` | 不传 |
| `dd options vip-levels` | `--session` | 不传 |
| `dd options associated-acts` | `--session` | 不传 |
| `dd options associated-acts` | `--game-type` | 必填 |
| `dd plugin list` | `--session` | 不传 |
| `dd plugin list` | `--keyword` | "" |
| `dd plugin list` | `--page` | 1 |
| `dd plugin list` | `--page-size` | 50 |
| `dd plugin list` | `--game-type` | 必填 |
| `dd plugin get` | `--session` | 不传 |
| `dd plugin get` | `--sn` | 必填 |
| `dd plugin categories` | `--session` | 不传 |
| `dd plugin game-versions` | `--session` | 不传 |
| `dd plugin game-versions` | `--game-type` | 必填 |
| `dd plugin versions` | `--session` | 不传 |
| `dd plugin versions` | `--sn` | 必填 |
| `dd plugin versions` | `--game-type` | 必填 |
| `dd plugin versions` | `--page` | 1 |
| `dd config list` | `--session` | 不传 |
| `dd config list` | `--keyword` | "" |
| `dd config list` | `--page` | 1 |
| `dd config list` | `--page-size` | 50 |
| `dd config list` | `--game-type` | 必填 |
| `dd config get` | `--session` | 不传 |
| `dd config get` | `--sn` | 必填 |
| `dd config backups` | `--session` | 不传 |
| `dd config backup-get` | `--session` | 不传 |
| `dd config backup-get` | `--sn` | 必填 |
| `dd wa list` | `--session` | 不传 |
| `dd wa list` | `--keyword` | "" |
| `dd wa list` | `--page` | 1 |
| `dd wa list` | `--page-size` | 50 |
| `dd wa list` | `--game-type` | 必填 |
| `dd wa get` | `--session` | 不传 |
| `dd wa get` | `--sn` | 必填 |
| `dd wa categories` | `--session` | 不传 |
| `dd wa categories` | `--game-type` | 必填 |

<a id="dd-backup-create"></a>
### `backup create`

Schema：`fupload.v1.dd.backup.create`。

接口：POST /backup/pre_create → 选中组对象PUT → POST /backup/finish_create；可再POST /backup/modify_name

条件和省略规则：只使用明确内容选择；create可复用bundle或生成后上传；删除前完整关联检查并逐项重查。

依据：DD100130 components.wow_ui.wow_ui_interface / frontend modules51154,58778; fupload/scripts/fupload_cli/dd_backup.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_dir` | `string` | 否/条件必填 | 拒绝 | 非空 | 仅本机选定游戏分支根目录；本地/备份管线 |
| `game_type` | `integer` | 否/条件必填 | 拒绝 | 最小 1 | pre_create.game_type；本地/备份管线 |
| `output_dir` | `string` | 否/条件必填 | 拒绝 | 非空 | 仅本机输出目录；本地/备份管线 |
| `addon_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pre_create.known_addon.items[].{name,modified,dirs}；本地/备份管线 |
| `unknown_addons` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pre_create.unknown_addon.items；本地/备份管线 |
| `materials` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pre_create.material.items[].{name,desc}；本地/备份管线 |
| `fonts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pre_create.font.items；本地/备份管线 |
| `include_wtf_root` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | 本地WTF根文件选择，进入wtf ZIP；本地/备份管线 |
| `wtf_accounts` | `array` | 否/条件必填 | 拒绝 | [{account,include_common,roles:[{server,name}]}]; exact role choices | pre_create.wtf.accounts[].{name,servers:[{name,items}]}及对应ZIP；本地/备份管线；账号项仅account/include_common/roles；角色项仅server/name |
| `bundle_file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | 仅本机读取、校验manifest和分组ZIP；本地/备份管线；必须含与账号/角色树及 ZIP 内容一致的本地 selection；不上传 selection。旧实验包缺失时需重新生成，拒绝猜测原选择。 |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 14 | modify_name.name（创建完成后明确改名）；本地/备份管线；备份名称最多14字符 |

字段映射依据：`fupload/scripts/fupload_cli/dd_backup.py:generate_backup/DDBackupMixin`。

<a id="dd-backup-delete"></a>
### `backup delete`

Schema：`fupload.v1.dd.backup.delete`。

接口：POST /backup/delete（逐项）

条件和省略规则：只使用明确内容选择；create可复用bundle或生成后上传；删除前完整关联检查并逐项重查。

依据：DD100130 components.wow_ui.wow_ui_interface / frontend modules51154,58778; fupload/scripts/fupload_cli/dd_backup.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_ids` | `array` | 是 | 拒绝 | 非空；最多项 1000 | delete.sn（逐项）；本地/备份管线 |
| `confirm_delete` | `boolean` | 是 | 拒绝 | 可选 `[true]` | 仅本机确认，不发接口；本地/备份管线 |

字段映射依据：`fupload/scripts/fupload_cli/dd_backup.py:generate_backup/DDBackupMixin`。

<a id="dd-backup-generate"></a>
### `backup generate`

Schema：`fupload.v1.dd.backup.generate`。

接口：本机生成，不请求服务器

条件和省略规则：只使用明确内容选择；create可复用bundle或生成后上传；删除前完整关联检查并逐项重查。

依据：DD100130 components.wow_ui.wow_ui_interface / frontend modules51154,58778; fupload/scripts/fupload_cli/dd_backup.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_dir` | `string` | 是 | 拒绝 | 非空 | 仅本机选定游戏分支根目录；本地/备份管线 |
| `game_type` | `integer` | 是 | 拒绝 | 最小 1 | pre_create.game_type；本地/备份管线 |
| `output_dir` | `string` | 是 | 拒绝 | 非空 | 仅本机输出目录；本地/备份管线 |
| `addon_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pre_create.known_addon.items[].{name,modified,dirs}；本地/备份管线 |
| `unknown_addons` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pre_create.unknown_addon.items；本地/备份管线 |
| `materials` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pre_create.material.items[].{name,desc}；本地/备份管线 |
| `fonts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | pre_create.font.items；本地/备份管线 |
| `include_wtf_root` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | 本地WTF根文件选择，进入wtf ZIP；本地/备份管线 |
| `wtf_accounts` | `array` | 否/条件必填 | 拒绝 | [{account,include_common,roles:[{server,name}]}]; exact role choices | pre_create.wtf.accounts[].{name,servers:[{name,items}]}及对应ZIP；本地/备份管线；账号项仅account/include_common/roles；角色项仅server/name |

字段映射依据：`fupload/scripts/fupload_cli/dd_backup.py:generate_backup/DDBackupMixin`。

<a id="dd-backup-rename"></a>
### `backup rename`

Schema：`fupload.v1.dd.backup.rename`。

接口：POST /backup/modify_name

条件和省略规则：只使用明确内容选择；create可复用bundle或生成后上传；删除前完整关联检查并逐项重查。

依据：DD100130 components.wow_ui.wow_ui_interface / frontend modules51154,58778; fupload/scripts/fupload_cli/dd_backup.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `sn` | `string` | 是 | 拒绝 | 非空 | modify_name.sn；本地/备份管线 |
| `name` | `string` | 是 | 拒绝 | 非空；最多字符 14 | modify_name.name（创建完成后明确改名）；本地/备份管线；备份名称最多14字符 |

字段映射依据：`fupload/scripts/fupload_cli/dd_backup.py:generate_backup/DDBackupMixin`。

<a id="dd-backup-upload"></a>
### `backup upload`

Schema：`fupload.v1.dd.backup.upload`。

接口：POST /backup/pre_create → 选中组对象PUT → POST /backup/finish_create；可再POST /backup/modify_name

条件和省略规则：只使用明确内容选择；create可复用bundle或生成后上传；删除前完整关联检查并逐项重查。

依据：DD100130 components.wow_ui.wow_ui_interface / frontend modules51154,58778; fupload/scripts/fupload_cli/dd_backup.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `bundle_file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | 仅本机读取、校验manifest和分组ZIP；本地/备份管线；必须含与账号/角色树及 ZIP 内容一致的本地 selection；不上传 selection。旧实验包缺失时需重新生成，拒绝猜测原选择。 |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 14 | modify_name.name（创建完成后明确改名）；本地/备份管线；备份名称最多14字符 |

字段映射依据：`fupload/scripts/fupload_cli/dd_backup.py:generate_backup/DDBackupMixin`。

<a id="dd-config-create"></a>
### `config create`

Schema：`fupload.v1.dd.config.create`。

接口：POST /share/create

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `scope` | `string` | 是 | 拒绝 | 可选 `["public", "private"]` | scope；最终JSON表单；private会规范化频道/VIP；配置当前实现没有插件/WA的assign_user_sn限制 |
| `title` | `string` | 是 | 拒绝 | 非空；最多字符 40 | title；最终JSON表单 |
| `brief_desc` | `string` | 是 | 拒绝 | 非空；最多字符 50 | brief_desc；最终JSON表单 |
| `desc` | `string` | 是 | 拒绝 | 非空 | desc；最终JSON表单 |
| `display_imgs` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | display_imgs；最终JSON表单 |
| `display_img_files` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | display_imgs；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `share_code_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | share_code_life_type；最终JSON表单；public插件/WA固定forever；public配置不发该字段；private从选项查询 |
| `need_buy` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | need_buy；最终JSON表单；true时必须price_fen和buy_life_type；public/private不能代替付费选择；已有对象外层付费模式锁定；配置wire为整数0/1，detail投影可为boolean |
| `price_fen` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | price_fen；最终JSON表单；单位分；0或10..20000；不是元；免费create归零 |
| `buy_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | buy_life_type；最终JSON表单 |
| `jump_room` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | jump_room；最终JSON表单；true时room_id必填；channel_id与channel_type同时空或同时非空；false清空房间/频道及sync_room |
| `room_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | room_id；最终JSON表单 |
| `channel_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_id；最终JSON表单 |
| `channel_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_type；最终JSON表单 |
| `sync_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | sync_room；最终JSON表单；true时需要jump_room与有效频道；private强制false |
| `creation_statement` | `string` | 是 | 拒绝 | 可选 `["original", "chinesize", "renovate", "second"]` | creation_statement；最终JSON表单；提交编辑器要求非空；取用户真实声明，不自动编造 |
| `with_associate` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | with_associate；最终JSON表单；true时associated_acts至少一项；false清空关联 |
| `associated_acts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | associated_acts；最终JSON表单；数组项仅sn:string、act_type:addon\|share\|wa；先查询候选 |
| `need_anchor_vip` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | need_anchor_vip；最终JSON表单；true时vip_levels非空；private强制false |
| `vip_levels` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | vip_levels；最终JSON表单 |
| `backup_sn` | `string` | 是 | 拒绝 | 非空 | backup_sn；最终JSON表单 |
| `update_desc` | `string` | 否/条件必填 | 拒绝 | 最多字符 1000 | update_desc；最终JSON表单 |
| `known_addon_ids` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | known_addon.items[]（按addon_id选中并复制完整候选）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `known_addon_update_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | known_addon.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `unknown_addon_ids` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | unknown_addon.items[]（标量按自身；对象按name，缺失才按id）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `unknown_addon_update_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknown_addon.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `wtf_role_ids` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | wtf.accounts[].servers[].items；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `material_names` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | material.items[]（按name选择完整候选）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `material_update_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | material.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `font_names` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | font.items[]（标量按自身；对象按name或id）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `font_update_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | font.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `known_wa_ids` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | known_wa.items[]（按uid选择完整候选）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `known_wa_update_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | known_wa.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `unknown_wa_ids` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | unknown_wa.items[]（按uid选择，id按选中WTF账号映射替换）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `unknown_wa_update_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknown_wa.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `retail_ui_config` | `object` | 否/条件必填 | 允许 | safe selector object: edit_mode_selectors, default_edit_mode_selector, cool_down_selectors, enable_dd_setup_wizard | retail_ui_config.edit_mode[account][] / cool_down[account][] / enable_dd_setup_wizard；最终JSON表单；输入仅稳定selector；本地查备份后wire发送原生对象，edit_mode补is_default；正式服切备份需重选 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:config_form`；`fupload/scripts/fupload_cli/dd.py:resolve_retail_ui_config`；`fupload/scripts/fupload_cli/dd.py:selected_group/_key/CONFIG_GROUPS/selected_wa_group`。

<a id="dd-config-delete"></a>
### `config delete`

Schema：`fupload.v1.dd.config.delete`。

接口：POST /share/delete

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `sn` | `string` | 是 | 拒绝 | 非空 | sn；最终JSON表单 |
| `confirm_delete` | `boolean` | 是 | 拒绝 | 可选 `[true]` | 仅本机删除确认，不发接口；写前校验 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:config_form`。

<a id="dd-config-edit"></a>
### `config edit`

Schema：`fupload.v1.dd.config.edit`。

接口：POST /share/modify

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `share_sn` | `string` | 是 | 拒绝 | 非空 | share_sn；最终JSON表单 |
| `scope` | `string` | 否/条件必填 | 拒绝 | 可选 `["public", "private"]` | scope；最终JSON表单；private会规范化频道/VIP；配置当前实现没有插件/WA的assign_user_sn限制 |
| `title` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 40 | title；最终JSON表单 |
| `brief_desc` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 50 | brief_desc；最终JSON表单 |
| `desc` | `string` | 否/条件必填 | 拒绝 | 非空 | desc；最终JSON表单 |
| `display_imgs` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | display_imgs；最终JSON表单 |
| `display_img_files` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | display_imgs；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `share_code_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | share_code_life_type；最终JSON表单；public插件/WA固定forever；public配置不发该字段；private从选项查询 |
| `need_buy` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | need_buy；最终JSON表单；true时必须price_fen和buy_life_type；public/private不能代替付费选择；已有对象外层付费模式锁定；配置wire为整数0/1，detail投影可为boolean |
| `price_fen` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | price_fen；最终JSON表单；单位分；0或10..20000；不是元；免费create归零 |
| `buy_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | buy_life_type；最终JSON表单 |
| `jump_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | jump_room；最终JSON表单；true时room_id必填；channel_id与channel_type同时空或同时非空；false清空房间/频道及sync_room |
| `room_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | room_id；最终JSON表单 |
| `channel_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_id；最终JSON表单 |
| `channel_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_type；最终JSON表单 |
| `sync_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | sync_room；最终JSON表单；true时需要jump_room与有效频道；private强制false |
| `creation_statement` | `string` | 否/条件必填 | 拒绝 | 可选 `["original", "chinesize", "renovate", "second"]` | creation_statement；最终JSON表单；提交编辑器要求非空；取用户真实声明，不自动编造 |
| `with_associate` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | with_associate；最终JSON表单；true时associated_acts至少一项；false清空关联 |
| `associated_acts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | associated_acts；最终JSON表单；数组项仅sn:string、act_type:addon\|share\|wa；先查询候选 |
| `need_anchor_vip` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | need_anchor_vip；最终JSON表单；true时vip_levels非空；private强制false |
| `vip_levels` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | vip_levels；最终JSON表单 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:config_form`。

<a id="dd-config-update"></a>
### `config update`

Schema：`fupload.v1.dd.config.update`。

接口：POST /share/modify

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `share_sn` | `string` | 是 | 拒绝 | 非空 | share_sn；最终JSON表单 |
| `backup_sn` | `string` | 是 | 拒绝 | 非空 | backup_sn；最终JSON表单 |
| `update_desc` | `string` | 是 | 拒绝 | 最多字符 1000 | update_desc；最终JSON表单 |
| `known_addon_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | known_addon.items[]（按addon_id选中并复制完整候选）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `known_addon_update_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | known_addon.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `unknown_addon_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknown_addon.items[]（标量按自身；对象按name，缺失才按id）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `unknown_addon_update_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknown_addon.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `wtf_role_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | wtf.accounts[].servers[].items；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `material_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | material.items[]（按name选择完整候选）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `material_update_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | material.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `font_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | font.items[]（标量按自身；对象按name或id）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `font_update_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | font.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `known_wa_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | known_wa.items[]（按uid选择完整候选）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `known_wa_update_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | known_wa.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `unknown_wa_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknown_wa.items[]（按uid选择，id按选中WTF账号映射替换）；从选定备份重建完整嵌套分组，不把选择ID数组原样透传 |
| `unknown_wa_update_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknown_wa.inner_version[选择键]；从选定备份重建完整嵌套分组，不把选择ID数组原样透传；必须为已选内容子集；已有非零版本标记更新则+1，其余保留，初始为1；WA键是uid，不是内部id |
| `retail_ui_config` | `object` | 否/条件必填 | 允许 | safe selector object: edit_mode_selectors, default_edit_mode_selector, cool_down_selectors, enable_dd_setup_wizard | retail_ui_config.edit_mode[account][] / cool_down[account][] / enable_dd_setup_wizard；最终JSON表单；输入仅稳定selector；本地查备份后wire发送原生对象，edit_mode补is_default；正式服切备份需重选 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:config_form`；`fupload/scripts/fupload_cli/dd.py:resolve_retail_ui_config`；`fupload/scripts/fupload_cli/dd.py:selected_group/_key/CONFIG_GROUPS/selected_wa_group`。

<a id="dd-plugin-create"></a>
### `plugin create`

Schema：`fupload.v1.dd.plugin.create`。

接口：POST /addon/create

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_type` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | game_type；最终JSON表单；插件create上下文固定；用game-types查询；不要混同游戏版本字符串 |
| `scope` | `string` | 是 | 拒绝 | 可选 `["public", "private"]` | scope；最终JSON表单；private会规范化商业/频道/VIP字段；assign_user_sn对象只能public |
| `addon_type` | `integer` | 是 | 拒绝 | 可选 `[0, 1]` | addon_type；最终JSON表单 |
| `name` | `string` | 是 | 拒绝 | 非空；最多字符 80 | name；最终JSON表单 |
| `description` | `string` | 是 | 拒绝 | 非空；最多字符 80 | description；最终JSON表单 |
| `logo` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | logo；最终JSON表单 |
| `logo_file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | logo；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `detail_imgs` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | detail_imgs；最终JSON表单 |
| `detail_img_files` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | detail_imgs；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `primary_category_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | primary_category_id；最终JSON表单 |
| `second_category_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | second_category_ids；最终JSON表单；先查询primary下候选；最终提交规范化后的子分类ID数组，不透传显示对象 |
| `html_desc` | `string` | 是 | 拒绝 | 非空 | html_desc；最终JSON表单 |
| `share_code_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | share_code_life_type；最终JSON表单；public插件/WA固定forever；public配置不发该字段；private从选项查询 |
| `need_buy` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | need_buy；最终JSON表单；true时必须price_fen和buy_life_type；public/private不能代替付费选择；已有对象外层付费模式锁定 |
| `price_fen` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | price_fen；最终JSON表单；单位分；0或10..20000；不是元；免费create归零 |
| `buy_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | buy_life_type；最终JSON表单 |
| `jump_room` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | jump_room；最终JSON表单；true时room_id必填；channel_id与channel_type同时空或同时非空；false清空房间/频道及sync_room |
| `room_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | room_id；最终JSON表单 |
| `channel_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_id；最终JSON表单 |
| `channel_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_type；最终JSON表单 |
| `sync_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | sync_room；最终JSON表单；true时需要jump_room与有效频道；private强制false |
| `creation_statement` | `string` | 是 | 拒绝 | 可选 `["original", "chinesize", "renovate", "second"]` | creation_statement；最终JSON表单；提交编辑器要求非空；取用户真实声明，不自动编造 |
| `with_associate` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | with_associate；最终JSON表单；true时associated_acts至少一项；false清空关联 |
| `associated_acts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | associated_acts；最终JSON表单；数组项仅sn:string、act_type:addon\|share\|wa；先查询候选 |
| `need_anchor_vip` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | need_anchor_vip；最终JSON表单；true时vip_levels非空；private强制false |
| `vip_levels` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | vip_levels；最终JSON表单 |
| `game_versions` | `array` | 是 | 拒绝 | 非空 | game_versions；最终JSON表单；当前game_type下的build字符串数组 |
| `detail_url` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | detail_url；最终JSON表单 |
| `file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | detail_url；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `release_type` | `integer` | 是 | 拒绝 | 可选 `[1, 2, 3]` | release_type；最终JSON表单；版本上传类型需当前动态候选，编辑元数据保留旧值 |
| `version` | `string` | 是 | 拒绝 | 非空；最多字符 80 | version；最终JSON表单；WA必须数字字符串；插件重复版本在上传前拒绝 |
| `update_desc` | `string` | 是 | 拒绝 | 非空；最多字符 1000 | update_desc；最终JSON表单 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:plugin_form/PLUGIN_OPEN_FIELDS`。

<a id="dd-plugin-delete"></a>
### `plugin delete`

Schema：`fupload.v1.dd.plugin.delete`。

接口：POST /addon/delete

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `sn` | `string` | 是 | 拒绝 | 非空 | sn；最终JSON表单 |
| `confirm_delete` | `boolean` | 是 | 拒绝 | 可选 `[true]` | 仅本机删除确认，不发接口；写前校验 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:plugin_form/PLUGIN_OPEN_FIELDS`。

<a id="dd-plugin-edit"></a>
### `plugin edit`

Schema：`fupload.v1.dd.plugin.edit`。

接口：POST /addon/modify

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `sn` | `string` | 是 | 拒绝 | 非空 | sn；最终JSON表单 |
| `scope` | `string` | 否/条件必填 | 拒绝 | 可选 `["public", "private"]` | scope；最终JSON表单；private会规范化商业/频道/VIP字段；assign_user_sn对象只能public |
| `share_code_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | share_code_life_type；最终JSON表单；public插件/WA固定forever；public配置不发该字段；private从选项查询 |
| `need_buy` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | need_buy；最终JSON表单；true时必须price_fen和buy_life_type；public/private不能代替付费选择；已有对象外层付费模式锁定 |
| `price_fen` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | price_fen；最终JSON表单；单位分；0或10..20000；不是元；免费create归零 |
| `buy_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | buy_life_type；最终JSON表单 |
| `jump_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | jump_room；最终JSON表单；true时room_id必填；channel_id与channel_type同时空或同时非空；false清空房间/频道及sync_room |
| `room_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | room_id；最终JSON表单 |
| `channel_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_id；最终JSON表单 |
| `channel_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_type；最终JSON表单 |
| `sync_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | sync_room；最终JSON表单；true时需要jump_room与有效频道；private强制false |
| `creation_statement` | `string` | 否/条件必填 | 拒绝 | 可选 `["original", "chinesize", "renovate", "second"]` | creation_statement；最终JSON表单；提交编辑器要求非空；取用户真实声明，不自动编造 |
| `with_associate` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | with_associate；最终JSON表单；true时associated_acts至少一项；false清空关联 |
| `associated_acts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | associated_acts；最终JSON表单；数组项仅sn:string、act_type:addon\|share\|wa；先查询候选 |
| `need_anchor_vip` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | need_anchor_vip；最终JSON表单；true时vip_levels非空；private强制false |
| `vip_levels` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | vip_levels；最终JSON表单 |
| `description` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 80 | description；最终JSON表单 |
| `logo` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | logo；最终JSON表单 |
| `logo_file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | logo；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `html_desc` | `string` | 否/条件必填 | 拒绝 | 非空 | html_desc；最终JSON表单 |
| `update_desc` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | update_desc；最终JSON表单 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:plugin_form/PLUGIN_OPEN_FIELDS`。

<a id="dd-plugin-update"></a>
### `plugin update`

Schema：`fupload.v1.dd.plugin.update`。

接口：POST /addon/modify

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `sn` | `string` | 是 | 拒绝 | 非空 | sn；最终JSON表单 |
| `game_versions` | `array` | 是 | 拒绝 | 非空 | game_versions；最终JSON表单；当前game_type下的build字符串数组 |
| `detail_url` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | detail_url；最终JSON表单 |
| `file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | detail_url；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `release_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 2, 3]` | release_type；最终JSON表单；版本上传类型需当前动态候选，编辑元数据保留旧值 |
| `version` | `string` | 是 | 拒绝 | 非空；最多字符 80 | version；最终JSON表单；WA必须数字字符串；插件重复版本在上传前拒绝 |
| `update_desc` | `string` | 是 | 拒绝 | 非空；最多字符 1000 | update_desc；最终JSON表单 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:plugin_form/PLUGIN_OPEN_FIELDS`。

<a id="dd-wa-create"></a>
### `wa create`

Schema：`fupload.v1.dd.wa.create`。

接口：POST /wa/create

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_type` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | game_type；最终JSON表单；插件create上下文固定；用game-types查询；不要混同游戏版本字符串 |
| `scope` | `string` | 是 | 拒绝 | 可选 `["public", "private"]` | scope；最终JSON表单；private会规范化商业/频道/VIP字段；assign_user_sn对象只能public |
| `name` | `string` | 是 | 拒绝 | 非空；最多字符 40 | name；最终JSON表单 |
| `game_version` | `string` | 是 | 拒绝 | 非空 | game_version；最终JSON表单 |
| `brief_desc` | `string` | 是 | 拒绝 | 非空；最多字符 50 | brief_desc；最终JSON表单 |
| `display_imgs` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | display_imgs；最终JSON表单 |
| `display_img_files` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | display_imgs；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `category_ids` | `array` | 是 | 拒绝 | 非空；最多项 5 | category_ids；最终JSON表单 |
| `desc` | `string` | 是 | 拒绝 | 非空 | desc；最终JSON表单 |
| `share_code_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | share_code_life_type；最终JSON表单；public插件/WA固定forever；public配置不发该字段；private从选项查询 |
| `need_buy` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | need_buy；最终JSON表单；true时必须price_fen和buy_life_type；public/private不能代替付费选择；已有对象外层付费模式锁定 |
| `price_fen` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | price_fen；最终JSON表单；单位分；0或10..20000；不是元；免费create归零 |
| `buy_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | buy_life_type；最终JSON表单 |
| `jump_room` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | jump_room；最终JSON表单；true时room_id必填；channel_id与channel_type同时空或同时非空；false清空房间/频道及sync_room |
| `room_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | room_id；最终JSON表单 |
| `channel_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_id；最终JSON表单 |
| `channel_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_type；最终JSON表单 |
| `sync_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | sync_room；最终JSON表单；true时需要jump_room与有效频道；private强制false |
| `creation_statement` | `string` | 是 | 拒绝 | 可选 `["original", "chinesize", "renovate", "second"]` | creation_statement；最终JSON表单；提交编辑器要求非空；取用户真实声明，不自动编造 |
| `with_associate` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | with_associate；最终JSON表单；true时associated_acts至少一项；false清空关联 |
| `associated_acts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | associated_acts；最终JSON表单；数组项仅sn:string、act_type:addon\|share\|wa；先查询候选 |
| `need_anchor_vip` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | need_anchor_vip；最终JSON表单；true时vip_levels非空；private强制false |
| `vip_levels` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | vip_levels；最终JSON表单 |
| `content` | `string` | 是 | 拒绝 | 非空 | content；最终JSON表单；!WA:2!由官方解析器生成parse_wa_uid/id；输入不接受这两个内部字段 |
| `update_desc` | `string` | 是 | 拒绝 | 非空；最多字符 1000 | update_desc；最终JSON表单 |
| `version` | `string` | 是 | 拒绝 | 非空；最多字符 80 | version；最终JSON表单；WA必须数字字符串；插件重复版本在上传前拒绝 |
| `with_file` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | with_file；最终JSON表单；true时需ZIP及安装路径，update省略可保留已有附件；false按官方表单保留内部路径 |
| `file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | file_path；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `file_install_path` | `string` | 否/条件必填 | 拒绝 | 可选 `["", "Interface", "Interface/Addons"]` | file_install_path；最终JSON表单 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:wa_form/WA_FIELDS`。

<a id="dd-wa-delete"></a>
### `wa delete`

Schema：`fupload.v1.dd.wa.delete`。

接口：POST /wa/delete

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `sn` | `string` | 是 | 拒绝 | 非空 | sn；最终JSON表单 |
| `confirm_delete` | `boolean` | 是 | 拒绝 | 可选 `[true]` | 仅本机删除确认，不发接口；写前校验 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:wa_form/WA_FIELDS`。

<a id="dd-wa-edit"></a>
### `wa edit`

Schema：`fupload.v1.dd.wa.edit`。

接口：POST /wa/modify

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `sn` | `string` | 是 | 拒绝 | 非空 | sn；最终JSON表单 |
| `game_type` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | game_type；最终JSON表单；插件create上下文固定；用game-types查询；不要混同游戏版本字符串 |
| `scope` | `string` | 否/条件必填 | 拒绝 | 可选 `["public", "private"]` | scope；最终JSON表单；private会规范化商业/频道/VIP字段；assign_user_sn对象只能public |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 40 | name；最终JSON表单 |
| `game_version` | `string` | 否/条件必填 | 拒绝 | 非空 | game_version；最终JSON表单 |
| `brief_desc` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 50 | brief_desc；最终JSON表单 |
| `display_imgs` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | display_imgs；最终JSON表单 |
| `display_img_files` | `array` | 否/条件必填 | 拒绝 | 最多项 8 | display_imgs；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `category_ids` | `array` | 否/条件必填 | 拒绝 | 非空；最多项 5 | category_ids；最终JSON表单 |
| `desc` | `string` | 否/条件必填 | 拒绝 | 非空 | desc；最终JSON表单 |
| `share_code_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | share_code_life_type；最终JSON表单；public插件/WA固定forever；public配置不发该字段；private从选项查询 |
| `need_buy` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | need_buy；最终JSON表单；true时必须price_fen和buy_life_type；public/private不能代替付费选择；已有对象外层付费模式锁定 |
| `price_fen` | `integer` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | price_fen；最终JSON表单；单位分；0或10..20000；不是元；免费create归零 |
| `buy_life_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | buy_life_type；最终JSON表单 |
| `jump_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | jump_room；最终JSON表单；true时room_id必填；channel_id与channel_type同时空或同时非空；false清空房间/频道及sync_room |
| `room_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | room_id；最终JSON表单 |
| `channel_id` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_id；最终JSON表单 |
| `channel_type` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | channel_type；最终JSON表单 |
| `sync_room` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | sync_room；最终JSON表单；true时需要jump_room与有效频道；private强制false |
| `creation_statement` | `string` | 否/条件必填 | 拒绝 | 可选 `["original", "chinesize", "renovate", "second"]` | creation_statement；最终JSON表单；提交编辑器要求非空；取用户真实声明，不自动编造 |
| `with_associate` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | with_associate；最终JSON表单；true时associated_acts至少一项；false清空关联 |
| `associated_acts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | associated_acts；最终JSON表单；数组项仅sn:string、act_type:addon\|share\|wa；先查询候选 |
| `need_anchor_vip` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | need_anchor_vip；最终JSON表单；true时vip_levels非空；private强制false |
| `vip_levels` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | vip_levels；最终JSON表单 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:wa_form/WA_FIELDS`。

<a id="dd-wa-update"></a>
### `wa update`

Schema：`fupload.v1.dd.wa.update`。

接口：POST /wa/modify

条件和省略规则：edit/update先读detail及作者列表，省略字段由实际重建表单保留；create按必填及条件收集。删除只发一次并读回。

依据：fupload/scripts/fupload_cli/dd.py; tests/test_dd_wire_matrix.py

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `sn` | `string` | 是 | 拒绝 | 非空 | sn；最终JSON表单 |
| `content` | `string` | 是 | 拒绝 | 非空 | content；最终JSON表单；!WA:2!由官方解析器生成parse_wa_uid/id；输入不接受这两个内部字段 |
| `update_desc` | `string` | 是 | 拒绝 | 非空；最多字符 1000 | update_desc；最终JSON表单 |
| `version` | `string` | 是 | 拒绝 | 非空；最多字符 80 | version；最终JSON表单；WA必须数字字符串；插件重复版本在上传前拒绝 |
| `with_file` | `boolean` | 是 | 拒绝 | 见动作条件及嵌套结构 | with_file；最终JSON表单；true时需ZIP及安装路径，update省略可保留已有附件；false按官方表单保留内部路径 |
| `file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | file_path；本地文件先经/file/upload授权及对象PUT，最终提交返回URL/路径；数组媒体追加现有图片 |
| `file_install_path` | `string` | 否/条件必填 | 拒绝 | 可选 `["", "Interface", "Interface/Addons"]` | file_install_path；最终JSON表单 |

字段映射依据：`fupload/scripts/fupload_cli/dd.py:wa_form/WA_FIELDS`。

<a id="blackbox"></a>
## 黑盒工坊

审计日期：2026-10-30。逐字段机器表见同目录 `blackbox.json`，每项含 wire、stage、condition、evidence；覆盖当前 `SCHEMAS` 注册的全部黑盒写入字段，并补充只读命令与 configuration 内部字段。类型、必填项由中央 schema 总表提供，此表记录字段如何进入协议。

### 来源与可复核位置

| 范围 | 一手代码 | 定位 |
| --- | --- | --- |
| 插件元数据、版本 | 已保存的官方 Open 前端 `static.max-c.com__index-B2qQ5GFk.js`；未给出产品版本号，不能标作2.10.19原生代码 | 第1行，PluginInfoForm.getFormData offset3749；ge/update offset868；PluginVersionList.M/upsert offset8824；B/delete offset9037 |
| 分享编辑与条件 | 安装版 Desktop2.10.19，`heybox.wow-workshop`1.1.3，SDK声明^1.2.0，`view/assets/index-C7aTznJw.js` | 第1行，ke offset13189；Yl offset12270；Xe/Ze offset4706 |
| 备份分配、凭据、完成保存 | 同版本扩展 `extension.mjs` | 第250行，createBackup offset2285946；credential offset2279110；finishUpload offset2286071 |
| 动态游戏分支 | 同版本扩展 `extension.mjs` | 第101行，JA中的GET调用 offset689680：`/wow/v2/dynamic_conf/`，target `heybox-workshop`，解析result.strappidInfos |
| WTF manifest | 同版本扩展 `extension.mjs` | 第88行 offset615560，RealmCharacters由WtfSubInfo映射Player/Realm |
| 原生签名 | app.asar `client-update-channel.store-DWqW8hAd.js` | 第4行 offset1883005，jrn/Wrn/Zrn，交错字符串截20再MD5 |
| 原生身份恢复 | app.asar `main-runtime-CQ5zr8us.js` | 第3021行 offset2794880，v8e；R/ce(VX)恢复，Ie/De检查cookie一致 |
| 当前官网登录 | 官方当前 `login-index.js`（ignored analyze/blackbox-phone-login） | 第1行 jn offset272138、JH offset534692、p$ offset549464；精确wire已实测的研究脚本与生产HTTP/auth模块一致 |

安装版资源根：`C:/Program Files (x86)/Qingfeng/Qingfeng/HeyboxDesktop/versions/2.10.19/resources`。所有 offset 为UTF-8解码后字符串索引。压缩文件一行很长，函数名及offset比整行摘录更容易复核。仓库实现证据为 `fupload/scripts/fupload_cli/blackbox.py`、`blackbox_config.py`、`blackbox_backup.py`、`blackbox_http.py`、`blackbox_auth.py` 的对应方法。

### 插件与版本

插件详情编辑先读当前 module，再合并9个发布字段。JSON snake_case 映射为平台 `logoUrl/categoryIds/officialUrl/coreFolders` 等 form 字段；`core_folders` 数组转逗号字符串。`desc` 保持完整文本；未提供的已有字段保留。UI在插件类型9时显示核心目录。

`plugin update` 是版本 upsert 的CLI别名，不是插件元数据编辑。版本字段为 `moduleId, versionId(更新时), name, type, gameVersions(逗号连接), fileUrl`，空业务query。`file` 是本地ZIP输入，经上传取得fileUrl后写版本；不是远程JSON字段。编辑不给新file/file_url时使用现版本fileUrlHeybox。删除只有一次POST，后续只读检查auditState/消失；请求失败或结果不稳定不自动重放。

插件列表官方前端仅一次读取moduleList，尚无其分页参数证据；版本列表已有offset/limit。CLI的version create/update入口和provider实现不能等同schema已注册动作：当前明确注册version.edit/delete，创建可由plugin.update无versionId完成。中央表应以schema实际注册为准。

### 配置分享

创建与更新的form只有 `configuration=JSON.stringify(完整对象)`，业务query是backup_id，更新再加share_id。删除复用update，query额外delete=1，没有configuration正文。

完整对象从经ID验证的备份开始构造。ID/IsClassic/Strappid不接受用户覆写；更换backup_id要求显式重选KnownAddons、UnknownAddons、WTFList、Materials、Fonts，避免继承旧角色。更新保留未改Article、UpdateLog、ThumbList及完整容器元数据；不是把稀疏patch直接送API。文件选择容器只能提交Files，容器Host/Path等沿用备份。

已落实官方本地提交条件：

- 至少选择一项插件、角色、材质或字体内容。
- Open=true至少一张ThumbList预览图。
- Title非空，且严格还原JS `replace(/[^\x00-\xff]/g,"ab").length<=70`。Latin-1字符权重1，BMP中码点>255字符权重2，astral字符因UTF-16 surrogate pair权重4。

官方编辑器当前把SubscribeLevel赋0；这只是已观察默认值，非0的业务语义未核实，不能推断服务端禁止非0。NeedsPush在官方代码中只为更新通知订阅者而设置；创建时效果未核实。ChatInviteCode官方来自选择房间的invite_code，CLI目前接受string但未再查询房间归属。

KnownAddons按ID、文件按Name、WTF按账号及Realm/Player检查属于绑定备份。当前没有逐字段强制比较调用者提供的KnownAddons或Files对象与原对象的每个元数据值，中央表不要把这个选择校验描述为“全部元数据不可改”。

### 备份

本地scan返回候选目录和明确账号/角色，不联网上传，也不通过目录名自动识别平台KnownAddons。generate/create要求显式四类选择数组；空数组表示不选。已知插件需真实平台brief `ID,Name,Strategy,VersionID`，而非自行猜ID。

unknown_addons从Interface/AddOns打包，materials从Interface打包，fonts仅Fonts内.ttf。wtf_accounts采用 `{name,characters:[{realm,player}]}`，映射Name/RealmCharacters/Characters。每账号ZIP包括选中角色与该账号共享rootfiles/SavedVariables，不包括其它角色目录。manifest记录每个archive字节数、MD5和SHA256；上传前校验路径、内容清单、角色与哈希绑定。

上传真实链路为：create_backup分配ID与MaxSize → 每archive按backup_id/file_type取临时COS凭据 → COS PUT且SDK retry=0、检查ETag=MD5 → save_user_configuration（query.backup_id，form.configuration=base64 UTF-8 JSON） → 从完整backupList按ID读回验证。file_type已证实unknownModules/wtf/materials/fonts。generate本地路径、output_dir、manifest_file不是直接API参数。

备份get没有单独接口，使用list完整对象按ID精确匹配。rename为query backup_id/new_name。批量删除是逐项remove请求，不是批量HTTP接口：先验证全部ID和目标游戏的全部现有分享，空页才视为分享列表完成；关联未知、重复分页、超页数均阻止删除；每项发送前重查引用，发送后有限次数轮询只读列表，默认最多10次、间隔2秒；已有verify_attempts/verify_interval可控制等待。列表接口本身是POST，轮询不重发remove或其它mutation。期间存在的服务端并发创建分享没有原子条件删除接口证据，不能声称跨客户端事务锁。

### 登录与续期

正式默认是纯HTTP与本机CurrentUser DPAPI，不启动浏览器、不隐式发短信。每个业务会话实例首次请求前GET restore_login一次，必须与已选账号UID一致，使用服务器expire_at及返回pkey更新。续期失败返回login_required，POST不重放。

SMS手机号使用固定官方1024位RSA PKCS1v15，加密+86与号码拼接结果。发验证码body为phone_num，登录query为code且body仍phone_num。本机config只允许借用acc_config.xhh_token_id的有效B设备凭据到内存，不借用客户端账户cookie认证，不接受调用者token/路径。它不是恢复会话的必需条件。

真正微信链是web_sso→官方微信OAuth页面/二维码→长轮询→服务端callback→wechat/state。get_qrcode_url/qr_state属于小黑盒App扫码，两者不能混用。OAuth参数与图片从本次官方响应提取并验证固定host/path。

active与pending分开加密，使用Windows用户绑定DPAPI。pending不覆盖active，确认登录成功后才切换。已有SMS主会话默认优先；旧微信单独文件需要显式选择。旧cookie期限不当作服务器期限，在restore得到expire_at前不保存v2迁移。设备B凭据不持久化到active/pending。

官网会在成功restore后重设本地7天cookie；风控SDK重新取deviceId后重设本地14天cookie。这不证明服务器无限滚动续期。未发现仅凭旧B的刷新API或refresh_token协议。

### 旧文档需删除或改写的条目

- “默认启动persistent Chromium、headless probe、过期后打开登录页”的描述已与正式默认不符。原blackbox_web兼容实现存在不等于正常登录路径会启动它。
- “完全不读desktop config”应收窄为“不借用desktop账户cookie认证”；SMS可读取固定本机官方设备风险字段。
- “1.14.1原生API工坊relogin，所以配置/备份不可复用”的旧结论不能外推到2.10.19或新网页会话；Open插件权限、配置分享权限、备份权限必须分别验证。
- 不将改本地cookie expiry写成服务端必然续期；不将SDK获取B/D转换写成旧B可独立续期。
- 不将scan目录候选写成已完成服务端插件识别；不将配置发布JSON和备份保存base64 JSON混为同一编码。

### 已明确的未知项

当前未验证：SubscribeLevel非0语义、NeedsPush创建语义、Strategies对象内部完整契约、插件moduleList是否存在未公开分页。2026-10-30动态接口当前返回6个分支；该列表应每次从服务器读取，不能视为永久固定全集。非0等级和NeedsPush创建语义未用远程写入验证。机器表相应condition标明未知，不能从原生UI默认值猜服务端限制。

### 2026-10-30 隔离实测验收

使用已有HTTP会话，仅操作本轮带唯一FuploadProbe标记的对象。初始备份、作者插件与6分支我的分享均为空。`options game-types` 真实返回 wowretail、wowclassicera、wowclassicwlk、wowclassictbc、wowanniversary、wowforever。

在wowretail和wowanniversary各生成一份unknown addon及WTF包，源目录同时有选中和未选角色；ZIP清单确认仅含选中角色，上传后ETag和完整备份读回确认。随后完成rename和私密分享create/update/edit；正文包含富文本与img，ThumbList使用官方静态图片。更新日志与标题后，正文、图片、WTF角色及插件选择均原样保留。两分支只显示各自分享，其余四分支无测试分享。两个备份在存在引用时，delete-preview均拒绝；实际delete入口返回backup_in_use，没有发送remove。

实测修复两处协议适配问题：COS Python SDK需要字符串ContentLength，否则requests在发送前抛InvalidHeader；分享列表摘要不返回BackupID，创建确认必须先取新分享详情再比对绑定。两者均新增可复现回归断言。

上述两份分享和备份已清理。随后对wowclassicera、wowclassicwlk、wowclassictbc、wowforever各用新marker完成最小unknown addon单ZIP生成→上传/完整读回→改名读回→删除预览→删除与负向读回；逐个完成清理后再进入下一分支，始终不积攒云备份。每次均确认返回Strappid匹配、IsClassic=true、WTFList为空。至此当前动态接口返回的全部6分支均完成真实备份生命周期。

经典旧世分支首次删除后列表短暂返回旧记录，首次确认给出verification_required；随后独立只读查询证实已删除，未重发删除请求。已为此补充有限只读轮询及回归测试。最终独立查询确认云备份数0、6分支我的分享均0，本轮共6份备份和2份私密分享全部清理，未修改已有对象。此验收覆盖配置/备份，不代表插件版本发布或非0订阅等级已经实测。

### 只读命令与输入参数

| 命令 | 参数 | 默认/必填 |
| --- | --- | --- |
| `blackbox session doctor` | 无额外参数 | — |
| `blackbox session login-status` | `--login-id` | 必填 |
| `blackbox options game-types` | 无额外参数 | — |
| `blackbox backup list` | 无额外参数 | — |
| `blackbox backup get` | `--backup-id` | 必填 |
| `blackbox backup scan` | `--game-dir` | 必填 |
| `blackbox backup scan` | `--strappid` | 必填 |
| `blackbox backup delete-preview` | `--backup-ids` | 不传 |
| `blackbox backup delete-preview` | `--backup-id` | 不传 |
| `blackbox backup delete-preview` | `--name-contains` | 不传 |
| `blackbox backup delete-preview` | `--name-equals` | 不传 |
| `blackbox backup delete-preview` | `--created-before` | 不传 |
| `blackbox backup delete-preview` | `--created-after` | 不传 |
| `blackbox config list` | `--strappid` | 必填 |
| `blackbox config get` | `--share-id` | 必填 |
| `blackbox plugin list` | 无额外参数 | — |
| `blackbox plugin get` | `--module-id` | 必填 |
| `blackbox plugin versions` | `--module-id` | 必填 |

<a id="blackbox-backup-create"></a>
### `backup create`

Schema：`fupload.v1.blackbox.backup.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_dir` | `string` | 否/条件必填 | 拒绝 | 非空 | 不发送路径；仅本地扫描/生成manifest与ZIP；local_package；output_dir必须在game_dir之外且不存在；拒绝symlink/reparse/traversal |
| `output_dir` | `string` | 否/条件必填 | 拒绝 | 非空 | 不发送路径；仅本地扫描/生成manifest与ZIP；local_package；output_dir必须在game_dir之外且不存在；拒绝symlink/reparse/traversal |
| `strappid` | `string` | 否/条件必填 | 拒绝 | 非空 | configuration.Strappid；IsClassic=(strappid!=wowretail)；local_package_then_backup_save；当前接受wow[a-z0-9_]+；服务端动态支持分支全集未静态锁死 |
| `unknown_addons` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | configuration.UnknownAddons.Files[].{Name,Size}; archive type=unknownModules; ZIP from Interface/AddOns；local_package_then_backup_save；显式名称数组，空数组表示不选；按清单归档；fonts仅.ttf；容器补Size/MD5/Host/Path |
| `materials` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | configuration.Materials.Files[].{Name,Size}; archive type=materials; ZIP from Interface；local_package_then_backup_save；显式名称数组，空数组表示不选；按清单归档；fonts仅.ttf；容器补Size/MD5/Host/Path |
| `fonts` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | configuration.Fonts.Files[].{Name,Size}; archive type=fonts; ZIP from Fonts；local_package_then_backup_save；显式名称数组，空数组表示不选；按清单归档；fonts仅.ttf；容器补Size/MD5/Host/Path |
| `known_addons` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | configuration.KnownAddons；local_package_then_backup_save；官方brief对象ID,Name,Strategy,VersionID；Strategy本地校验1..5；scan只返回目录候选，不能自动识别known，调用者需提供真实平台brief |
| `strategies` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | configuration.Strategies；local_package_then_backup_save；array<object>原样；当前只核验对象数组，内部策略字段unknown；不是已验证任意键全集 |
| `wtf_accounts` | `array` | 否/条件必填 | 拒绝 | [{name,characters:[{realm,player}]}]; every account requires explicit characters | configuration.WTFList[].Name/Characters/RealmCharacters；每账户archive file_type=wtf；local_package_then_backup_save；[{name,characters:[{realm,player}]}]→{Name,RealmCharacters:[{Realm,Player}],Characters:[Realm - Player]}；只打选中角色+同账号rootfiles/SavedVariables，不含其它角色 |
| `file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | 本地backup.json包→与backup.upload相同链路；local_package_then_upload；与game_dir/选择等generation字段互斥；给file则直接upload；不给file则先generate |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_backup.py:backup_generate/backup_upload; Desktop2.10.19 heybox.wow-workshop1.1.3 extension.mjs createBackup/finishUpload/doProcessUpload`。

<a id="blackbox-backup-delete"></a>
### `backup delete`

Schema：`fupload.v1.blackbox.backup.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_ids` | `array` | 是 | 拒绝 | 非空；最多项 1000 | 逐项POST /wow/remove_user_configuration_backup/ query.backup_id；backup_delete；不是批量HTTP；预先验证所有ID和分享引用；逐项重新检查引用；遇不确定关联/分页中断则停止；逐项读回确认；remove仅一次；若列表暂留记录，仅轮询POST get_user_configuration_backup_list（只读），默认最多10次间隔2秒；耗尽仍verification_required，不重发mutation |
| `confirm_delete` | `boolean` | 是 | 拒绝 | 可选 `[true]` | 不发送；local_confirmation；必须true |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_config.py:_backup_delete_plan/backup_delete`；`fupload/scripts/fupload_cli/blackbox_config.py:backup_delete`。

<a id="blackbox-backup-generate"></a>
### `backup generate`

Schema：`fupload.v1.blackbox.backup.generate`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_dir` | `string` | 是 | 拒绝 | 非空 | 不发送路径；仅本地扫描/生成manifest与ZIP；local_package；output_dir必须在game_dir之外且不存在；拒绝symlink/reparse/traversal |
| `output_dir` | `string` | 是 | 拒绝 | 非空 | 不发送路径；仅本地扫描/生成manifest与ZIP；local_package；output_dir必须在game_dir之外且不存在；拒绝symlink/reparse/traversal |
| `strappid` | `string` | 是 | 拒绝 | 非空 | configuration.Strappid；IsClassic=(strappid!=wowretail)；local_package_then_backup_save；当前接受wow[a-z0-9_]+；服务端动态支持分支全集未静态锁死 |
| `unknown_addons` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | configuration.UnknownAddons.Files[].{Name,Size}; archive type=unknownModules; ZIP from Interface/AddOns；local_package_then_backup_save；显式名称数组，空数组表示不选；按清单归档；fonts仅.ttf；容器补Size/MD5/Host/Path |
| `materials` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | configuration.Materials.Files[].{Name,Size}; archive type=materials; ZIP from Interface；local_package_then_backup_save；显式名称数组，空数组表示不选；按清单归档；fonts仅.ttf；容器补Size/MD5/Host/Path |
| `fonts` | `array` | 是 | 拒绝 | 见动作条件及嵌套结构 | configuration.Fonts.Files[].{Name,Size}; archive type=fonts; ZIP from Fonts；local_package_then_backup_save；显式名称数组，空数组表示不选；按清单归档；fonts仅.ttf；容器补Size/MD5/Host/Path |
| `known_addons` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | configuration.KnownAddons；local_package_then_backup_save；官方brief对象ID,Name,Strategy,VersionID；Strategy本地校验1..5；scan只返回目录候选，不能自动识别known，调用者需提供真实平台brief |
| `strategies` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | configuration.Strategies；local_package_then_backup_save；array<object>原样；当前只核验对象数组，内部策略字段unknown；不是已验证任意键全集 |
| `wtf_accounts` | `array` | 是 | 拒绝 | [{name,characters:[{realm,player}]}]; every account requires explicit characters | configuration.WTFList[].Name/Characters/RealmCharacters；每账户archive file_type=wtf；local_package_then_backup_save；[{name,characters:[{realm,player}]}]→{Name,RealmCharacters:[{Realm,Player}],Characters:[Realm - Player]}；只打选中角色+同账号rootfiles/SavedVariables，不含其它角色 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_backup.py:backup_generate/backup_upload; Desktop2.10.19 heybox.wow-workshop1.1.3 extension.mjs createBackup/finishUpload/doProcessUpload`。

<a id="blackbox-backup-rename"></a>
### `backup rename`

Schema：`fupload.v1.blackbox.backup.rename`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_id` | `string` | 是 | 拒绝 | 非空 | POST /wow/rename_user_configuration_backup/ query.backup_id；backup_rename；先list精确ID匹配，再逐次读回Name |
| `name` | `string` | 是 | 拒绝 | 非空；最多字符 200 | POST /wow/rename_user_configuration_backup/ query.new_name；backup_rename；非空string |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_config.py:backup_rename`。

<a id="blackbox-backup-upload"></a>
### `backup upload`

Schema：`fupload.v1.blackbox.backup.upload`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | 本地manifest+ZIP验证→POST create_backup分配ID→POST get_user_backup_credential query{backup_id,file_type}→COS PUT→POST save_user_configuration query.backup_id + form.configuration=base64(JSON)；backup_upload；file不是直接上载到单一API；ID来自服务端；MaxSize核验源字节；COS MD5/ETag及最终list完整对象读回；不重放失败写；COS ContentLength转str匹配Python requests；SDK retry=0且ETag校验；2026-10-30动态接口当前返回的6分支均真实上传/改名/删除/读回及清理 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_backup.py:backup_generate/backup_upload; Desktop2.10.19 heybox.wow-workshop1.1.3 extension.mjs createBackup/finishUpload/doProcessUpload`。

<a id="blackbox-config-create"></a>
### `config create`

Schema：`fupload.v1.blackbox.config.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_id` | `string` | 是 | 拒绝 | 非空 | query.backup_id；同时绑定完整configuration.ID/IsClassic/Strappid；share_write；create必填；update默认现BackupID；更换备份须显式重选五类内容，不继承旧角色；创建后owned摘要缺BackupID时读取detail确认绑定，不重发create |
| `configuration` | `object` | 是 | 拒绝 | 非空 | form.configuration=JSON.stringify(完整绑定备份+已有分享内容+稀疏patch)；share_write；create→POST /wow/create_config_share/；update/edit→POST /wow/update_config_share/。ID/IsClassic/Strappid来自经验证backup，调用者不可覆盖；创建后owned摘要缺BackupID时读取detail确认绑定，不重发create |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl`。

<a id="blackbox-config-delete"></a>
### `config delete`

Schema：`fupload.v1.blackbox.config.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `share_id` | `string` | 是 | 拒绝 | 非空 | POST /wow/update_config_share/ query.share_id + current.BackupID + delete=1；无configuration正文；share_delete；先完整枚举当前账号该游戏分享确认归属；删除后读回列表确认 |
| `confirm_delete` | `boolean` | 是 | 拒绝 | 可选 `[true]` | 不发送；local_confirmation；必须true；CLI schema约束 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_config.py:config_delete`；`fupload/scripts/fupload_cli/schema.py:blackbox.config.delete`。

<a id="blackbox-config-edit"></a>
### `config edit`

Schema：`fupload.v1.blackbox.config.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_id` | `string` | 否/条件必填 | 拒绝 | 非空 | query.backup_id；同时绑定完整configuration.ID/IsClassic/Strappid；share_write；create必填；update默认现BackupID；更换备份须显式重选五类内容，不继承旧角色 |
| `configuration` | `object` | 是 | 拒绝 | 非空 | form.configuration=JSON.stringify(完整绑定备份+已有分享内容+稀疏patch)；share_write；create→POST /wow/create_config_share/；update/edit→POST /wow/update_config_share/。ID/IsClassic/Strappid来自经验证backup，调用者不可覆盖 |
| `share_id` | `string` | 是 | 拒绝 | 非空 | query.share_id；share_write；先GET语义POST /wow/v2/share/detail/，核验ShareID/BackupID并保留富文本/图片 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl`。

<a id="blackbox-config-update"></a>
### `config update`

Schema：`fupload.v1.blackbox.config.update`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_id` | `string` | 否/条件必填 | 拒绝 | 非空 | query.backup_id；同时绑定完整configuration.ID/IsClassic/Strappid；share_write；create必填；update默认现BackupID；更换备份须显式重选五类内容，不继承旧角色 |
| `configuration` | `object` | 是 | 拒绝 | 非空 | form.configuration=JSON.stringify(完整绑定备份+已有分享内容+稀疏patch)；share_write；create→POST /wow/create_config_share/；update/edit→POST /wow/update_config_share/。ID/IsClassic/Strappid来自经验证backup，调用者不可覆盖 |
| `share_id` | `string` | 是 | 拒绝 | 非空 | query.share_id；share_write；先GET语义POST /wow/v2/share/detail/，核验ShareID/BackupID并保留富文本/图片 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl`。

<a id="blackbox-plugin-edit"></a>
### `plugin edit`

Schema：`fupload.v1.blackbox.plugin.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module/update/ form.id；module_update；读取module后合并；未提供值保持原值；form不是JSON正文 |
| `name` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module/update/ form.name；module_update；读取module后合并；未提供值保持原值；form不是JSON正文 |
| `logo_url` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module/update/ form.logoUrl；module_update；读取module后合并；未提供值保持原值；form不是JSON正文 |
| `category_ids` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module/update/ form.categoryIds；module_update；读取module后合并；未提供值保持原值；form不是JSON正文 |
| `type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 9]` | POST /wow/open_platform/module/update/ form.type；module_update；读取module后合并；未提供值保持原值；form不是JSON正文 |
| `desc` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module/update/ form.desc；module_update；读取module后合并；未提供值保持原值；form不是JSON正文 |
| `official` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module/update/ form.official；module_update；读取module后合并；未提供值保持原值；form不是JSON正文 |
| `official_url` | `string` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module/update/ form.officialUrl；module_update；读取module后合并；未提供值保持原值；form不是JSON正文 |
| `core_folders` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module/update/ form.coreFolders；module_update；稀疏输入先读完整module；core_folders数组join逗号；type9整合插件UI显示coreFolders。保留未改字段；id不改绑 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox.py:module_edit; captured Open frontend static.max-c.com__index-B2qQ5GFk.js PluginInfoForm.getFormData / ge`。

<a id="blackbox-plugin-update"></a>
### `plugin update`

Schema：`fupload.v1.blackbox.plugin.update`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `module_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module_version/upsert/ form.moduleId；version_upsert；version_id存在时更新；无version_id创建；module_id绑定所属模块 |
| `name` | `string` | 是 | 拒绝 | 非空 | POST /wow/open_platform/module_version/upsert/ form.name；version_upsert；version_id存在时更新；无version_id创建；module_id绑定所属模块 |
| `type` | `integer` | 是 | 拒绝 | 可选 `[1, 2, 3]` | POST /wow/open_platform/module_version/upsert/ form.type；version_upsert；version_id存在时更新；无version_id创建；module_id绑定所属模块 |
| `game_versions` | `array` | 是 | 拒绝 | 非空 | POST /wow/open_platform/module_version/upsert/ form.gameVersions；version_upsert；game_versions join逗号 |
| `file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | POST /wow/cos/upload/token/ form.jsonData=JSON.stringify({upload_infos:[{filename,file_size:bytes/1024/1024,type:module}]}); COS archive URL→upsert form.fileUrl；archive_upload；本地ZIP存在且有效；file优先覆盖file_url；COS上传与metadata更新为不同步骤；上传失败不写metadata |
| `file_url` | `string` | 否/条件必填 | 拒绝 | 非空 | POST /wow/open_platform/module_version/upsert/ form.fileUrl；version_upsert；file上传优先；edit未给新file/file_url时保留当前fileUrlHeybox |

字段映射依据：`fupload/scripts/fupload_cli/blackbox.py:upload_zip/_upload_zip_legacy; fupload/scripts/fupload_cli/blackbox.py:version_upsert; captured Open frontend index-B2qQ5GFk.js PluginVersionList.M / be`；`fupload/scripts/fupload_cli/blackbox.py:version_upsert; captured Open frontend index-B2qQ5GFk.js PluginVersionList.M / be`。

<a id="blackbox-session-forget"></a>
### `session forget`

Schema：`fupload.v1.blackbox.session.forget`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `confirm_forget` | `boolean` | 是 | 拒绝 | 可选 `[true]` | 不发送；本机删除/tombstone防旧会话复活；local_auth_control；必须true；不调用远程logout；不影响其它平台 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_auth.py; current official login-index.js JH.C/JH.w/JH.S/p$.runCallback; blackbox_http.py:HttpClient/Store/apply_session`。

<a id="blackbox-session-login-start"></a>
### `session login-start`

Schema：`fupload.v1.blackbox.session.login-start`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `method` | `string` | 是 | 拒绝 | 可选 `["sms", "wechat"]` | 不直接发wire；选择sms或wechat官方状态机；local_auth_control；不会由业务命令隐式启动；微信与小黑盒App QR不同 |
| `phone` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 11；SMS only; mainland China mobile number, supplied through input JSON. | POST /account/get_login_code/ form.phone_num=base64(RSA1024 PKCS1v15(+86+phone))；auth_sms；空业务query；本机固定config的device B只在内存借用；非账户cookie；不自动重发 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_auth.py; current official login-index.js JH.C/JH.w/JH.S/p$.runCallback; blackbox_http.py:HttpClient/Store/apply_session`。

<a id="blackbox-session-login-submit"></a>
### `session login-submit`

Schema：`fupload.v1.blackbox.session.login-submit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `login_id` | `string` | 是 | 拒绝 | 非空；最多字符 32；Opaque ID from login-start; 32 lowercase hexadecimal characters. | 不发送；匹配本机DPAPI pending.login_id；local_auth_control；opaque32hex，必须匹配未过期SMS pending |
| `code` | `string` | 是 | 拒绝 | 非空；最多字符 8；4-8 digit SMS code, supplied through --input PATH\|-; never an argv flag. | POST /account/login_code/ query.code；form.phone_num复用已加密手机号；auth_sms；4-8digits只从JSON输入；不落凭据明文/不放argv；不重放 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox_auth.py; current official login-index.js JH.C/JH.w/JH.S/p$.runCallback; blackbox_http.py:HttpClient/Store/apply_session`。

<a id="blackbox-session-renew"></a>
### `session renew`

Schema：`fupload.v1.blackbox.session.renew`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |

<a id="blackbox-version-delete"></a>
### `version delete`

Schema：`fupload.v1.blackbox.version.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `version_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module_version/delete/ form.versionId；version_delete；空业务query；单次写入后只读确认，不重放 |
| `module_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module_version/delete/ form.moduleId；version_delete；空业务query；单次写入后只读确认，不重放 |

字段映射依据：`fupload/scripts/fupload_cli/blackbox.py:version_delete; index-B2qQ5GFk.js PluginVersionList.B / Ae`。

<a id="blackbox-version-edit"></a>
### `version edit`

Schema：`fupload.v1.blackbox.version.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `version_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module_version/upsert/ form.versionId；version_upsert；version_id存在时更新；无version_id创建；module_id绑定所属模块 |
| `module_id` | `integer` | 是 | 拒绝 | 见动作条件及嵌套结构 | POST /wow/open_platform/module_version/upsert/ form.moduleId；version_upsert；version_id存在时更新；无version_id创建；module_id绑定所属模块 |
| `name` | `string` | 是 | 拒绝 | 非空 | POST /wow/open_platform/module_version/upsert/ form.name；version_upsert；version_id存在时更新；无version_id创建；module_id绑定所属模块 |
| `type` | `integer` | 是 | 拒绝 | 可选 `[1, 2, 3]` | POST /wow/open_platform/module_version/upsert/ form.type；version_upsert；version_id存在时更新；无version_id创建；module_id绑定所属模块 |
| `game_versions` | `array` | 是 | 拒绝 | 非空 | POST /wow/open_platform/module_version/upsert/ form.gameVersions；version_upsert；game_versions join逗号 |
| `file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | POST /wow/cos/upload/token/ form.jsonData=JSON.stringify({upload_infos:[{filename,file_size:bytes/1024/1024,type:module}]}); COS archive URL→upsert form.fileUrl；archive_upload；本地ZIP存在且有效；file优先覆盖file_url；COS上传与metadata更新为不同步骤；上传失败不写metadata |
| `file_url` | `string` | 否/条件必填 | 拒绝 | 非空 | POST /wow/open_platform/module_version/upsert/ form.fileUrl；version_upsert；file上传优先；edit未给新file/file_url时保留当前fileUrlHeybox |

字段映射依据：`fupload/scripts/fupload_cli/blackbox.py:upload_zip/_upload_zip_legacy; fupload/scripts/fupload_cli/blackbox.py:version_upsert; captured Open frontend index-B2qQ5GFk.js PluginVersionList.M / be`；`fupload/scripts/fupload_cli/blackbox.py:version_upsert; captured Open frontend index-B2qQ5GFk.js PluginVersionList.M / be`。

### 补充嵌套或协议字段

以下不是额外的顶层 JSON 字段；是否可由用户填写，以对应对象结构和动作说明为准。

| 字段路径 | 接口字段/用途 | 条件 | 依据 |
| --- | --- | --- | --- |
| `*.*.dry_run` | 不发送dry_run字段 | 不执行业务mutation；可能读取依赖对象；generate dry_run不写本地包 | `blackbox.py:execute_write; blackbox_config.py/blackbox_backup.py` |
| `*.*.schema` | 不发送 | 仅JSON schema版本标记 | `schema.py:Schema.validate; provider doc filtering` |
| `backup.delete-preview.backup_id` | 不发送筛选字段；本地filter backupList[].ID/Name/SaveTime后计算引用 | ID与筛选互斥；before/after严格<或> Unix秒；需枚举每目标游戏自己的全部分享；空页才完结 | `fupload/scripts/fupload_cli/blackbox_config.py:_backup_delete_plan/_config_rows` |
| `backup.delete-preview.backup_ids` | 不发送筛选字段；本地filter backupList[].ID/Name/SaveTime后计算引用 | ID与筛选互斥；before/after严格<或> Unix秒；需枚举每目标游戏自己的全部分享；空页才完结 | `fupload/scripts/fupload_cli/blackbox_config.py:_backup_delete_plan/_config_rows` |
| `backup.delete-preview.created_after` | 不发送筛选字段；本地filter backupList[].ID/Name/SaveTime后计算引用 | ID与筛选互斥；before/after严格<或> Unix秒；需枚举每目标游戏自己的全部分享；空页才完结 | `fupload/scripts/fupload_cli/blackbox_config.py:_backup_delete_plan/_config_rows` |
| `backup.delete-preview.created_before` | 不发送筛选字段；本地filter backupList[].ID/Name/SaveTime后计算引用 | ID与筛选互斥；before/after严格<或> Unix秒；需枚举每目标游戏自己的全部分享；空页才完结 | `fupload/scripts/fupload_cli/blackbox_config.py:_backup_delete_plan/_config_rows` |
| `backup.delete-preview.name_contains` | 不发送筛选字段；本地filter backupList[].ID/Name/SaveTime后计算引用 | ID与筛选互斥；before/after严格<或> Unix秒；需枚举每目标游戏自己的全部分享；空页才完结 | `fupload/scripts/fupload_cli/blackbox_config.py:_backup_delete_plan/_config_rows` |
| `backup.delete-preview.name_equals` | 不发送筛选字段；本地filter backupList[].ID/Name/SaveTime后计算引用 | ID与筛选互斥；before/after严格<或> Unix秒；需枚举每目标游戏自己的全部分享；空页才完结 | `fupload/scripts/fupload_cli/blackbox_config.py:_backup_delete_plan/_config_rows` |
| `backup.get.backup_id` | 无单独get；POST /wow/get_user_configuration_backup_list/ 后按backupList[].ID精确匹配 | 完整对象原样读取 | `fupload/scripts/fupload_cli/blackbox.py:execute_read; blackbox_config.py; blackbox_backup.py:backup_scan` |
| `backup.list.*` | POST /wow/get_user_configuration_backup_list/，无业务query/body | result.backupList完整对象；官方无独立get或分页调用 | `blackbox_config.py:_backup_rows; Desktop2.10.19 extension/view API adapter` |
| `backup.scan.game_dir` | 不发送；本地目录扫描 | 返回候选目录与角色，不自动全选 | `fupload/scripts/fupload_cli/blackbox.py:execute_read; blackbox_config.py; blackbox_backup.py:backup_scan` |
| `backup.scan.strappid` | 不发送；仅扫描结果上下文 | 调用者指定游戏分支 | `fupload/scripts/fupload_cli/blackbox.py:execute_read; blackbox_config.py; blackbox_backup.py:backup_scan` |
| `config.*.configuration.Article` | JSON.parse(form.configuration).Article | 富文本string，原样传递；update未改则保留字节内容，不截HTML | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.ChatInviteCode` | JSON.parse(form.configuration).ChatInviteCode | string；官方来自get_user_room_list选择房间invite_code；当前CLI未额外核验房间归属 | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.ClearFonts` | JSON.parse(form.configuration).ClearFonts | boolean；是否清空目标对应类别，不是自动全选；create默认false | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.ClearKnownAddons` | JSON.parse(form.configuration).ClearKnownAddons | boolean；是否清空目标对应类别，不是自动全选；create默认false | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.ClearMaterials` | JSON.parse(form.configuration).ClearMaterials | boolean；是否清空目标对应类别，不是自动全选；create默认false | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.ClearUnknownAddons` | JSON.parse(form.configuration).ClearUnknownAddons | boolean；是否清空目标对应类别，不是自动全选；create默认false | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.Fonts` | JSON.parse(form.configuration).Fonts | {Files:[完整已选文件对象]}；保留绑定备份容器其它元数据；Files空则发布正文省略容器；核验Name属于backup | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.ID/IsClassic/Strappid` | unknown as caller input: explicitly prohibited | 仅从backup继承，不是schema可写字段 | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.KnownAddons` | JSON.parse(form.configuration).KnownAddons | array<object>从绑定备份选择；WTF每账号必须显式RealmCharacters[{Realm,Player}]；KnownAddons核验ID | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.Materials` | JSON.parse(form.configuration).Materials | {Files:[完整已选文件对象]}；保留绑定备份容器其它元数据；Files空则发布正文省略容器；核验Name属于backup | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.NeedsPush` | JSON.parse(form.configuration).NeedsPush | boolean；官方ke只在更新时赋通知订阅者选择；create中该字段效果unknown | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.Open` | JSON.parse(form.configuration).Open | boolean；true需ThumbList非空；与公开审核有关 | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.SubscribeLevel` | JSON.parse(form.configuration).SubscribeLevel | integer>=0；当前官方ke仅赋0，非0业务语义unknown，未据UI默认值禁用 | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.ThumbList` | JSON.parse(form.configuration).ThumbList | array<string>图片引用；Open=true至少1张；保留已有引用及query | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.Title` | JSON.parse(form.configuration).Title | 非空；官方JS title.replace(/[^\x00-\xff]/g,ab).length<=70，Latin-1权重1、BMP>255权重2、astral权重4；provider已验证 | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.UnknownAddons` | JSON.parse(form.configuration).UnknownAddons | {Files:[完整已选文件对象]}；保留绑定备份容器其它元数据；Files空则发布正文省略容器；核验Name属于backup | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.UpdateLog` | JSON.parse(form.configuration).UpdateLog | 富文本string，原样传递；update未改则保留字节内容，不截HTML | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.*.configuration.WTFList` | JSON.parse(form.configuration).WTFList | array<object>从绑定备份选择；WTF每账号必须显式RealmCharacters[{Realm,Player}]；KnownAddons核验ID | `fupload/scripts/fupload_cli/blackbox_config.py:config_upsert/_validate_selection; Desktop2.10.19 heybox.wow-workshop1.1.3 view/assets/index-C7aTznJw.js ke/Yl/Hl` |
| `config.get.share_id` | POST /wow/v2/share/detail/ query.share_id | 检查返回ShareID/BackupID | `fupload/scripts/fupload_cli/blackbox.py:execute_read; blackbox_config.py; blackbox_backup.py:backup_scan` |
| `config.list.strappid` | POST /wow/v2/share/list/ query.strappid + offset/limit + sort_by=weekDownloadNum + my_publish=1 | 仅当前用户发布，空页才complete | `fupload/scripts/fupload_cli/blackbox.py:execute_read; blackbox_config.py; blackbox_backup.py:backup_scan` |
| `options.game-types.*` | GET /wow/v2/dynamic_conf/ → result.strappidInfos | 每次读取服务器动态列表；2026-10-30实测6分支wowretail/wowclassicera/wowclassicwlk/wowclassictbc/wowanniversary/wowforever；不是永久固定枚举；6分支均完成最小合成备份真实生命周期并清理，正式服/周年服另完成私密分享CRUD及引用保护 | `blackbox.py:execute_read options/game-types; Desktop2.10.19 heybox.wow-workshop1.1.3 extension.mjs line101 JA GET call offset689680, target heybox-workshop, result.strappidInfos; isolated live acceptance 2026-10-30` |
| `plugin.get.module_id` | GET /wow/open_platform/module/detail/ query.moduleId | 读取module和分页versionList | `fupload/scripts/fupload_cli/blackbox.py:execute_read; blackbox_config.py; blackbox_backup.py:backup_scan` |
| `plugin.list.*` | GET /wow/open_platform/module/list/，无业务query/body | result.moduleList；endpoint是否分页的当前前端证据仅一次请求，未伪造跨页接口 | `blackbox.py:plugin_list; Open frontend index-B2qQ5GFk.js` |
| `plugin.versions.module_id` | GET /wow/open_platform/module_version/list/ query.moduleId + offset/limit | 去重推进；达到明确total或短页/空页完结 | `fupload/scripts/fupload_cli/blackbox.py:execute_read; blackbox_config.py; blackbox_backup.py:backup_scan` |
| `session.login-status.login_id` | 不发送login_id；微信status发送固定长轮询uuid/last/_或读取本机pending状态 | 仅复用已有pending，不新建QR；状态完成才激活新会话 | `fupload/scripts/fupload_cli/blackbox_auth.py; current official login-index.js JH.C/JH.w/JH.S/p$.runCallback; blackbox_http.py:HttpClient/Store/apply_session` |
| `session.renew.*` | GET /account/restore_login，空业务query、无body；同cookiejar与website公共query | 核对已存UID一致，使用服务器expire_at；返回pkey覆盖4cookie；一次恢复成功不代表无限服务端续期 | `fupload/scripts/fupload_cli/blackbox_auth.py; current official login-index.js JH.C/JH.w/JH.S/p$.runCallback; blackbox_http.py:HttpClient/Store/apply_session` |
| `session.storage.*` | 不发送本机路径/DPAPI密文；cookie仅发匹配官方HTTPS域 | CurrentUser DPAPI；active/pending分离；默认SMS旧主会话优先；微信显式选择；risk不写active/pending | `blackbox_http.py:Store/_jar/_send` |
| `session.wechat.*` | GET api/account/wechat/login/v2/web_sso/?redirect_url=LOGIN&src=1(整体编码)→官方Location open.weixin.qq.com/connect/qrconnect→真实/connect/qrcode/uuid和long.open.weixin.qq.com/connect/l/qrconnect→官方callback→GET /account/wechat/state/ query{_notip:true,heybox_id:empty} | appid/state/callback/uuid均从当前官方响应提取并校验固定host/path；不猜appid；无浏览器；image只保存官方PNG/JPEG | `fupload/scripts/fupload_cli/blackbox_auth.py; current official login-index.js JH.C/JH.w/JH.S/p$.runCallback; blackbox_http.py:HttpClient/Store/apply_session` |

<a id="modus"></a>
## ModUs 与 Creator

Creator 证据来自官方 DLL 0.1.6.0 的 IL；主客户端提取包的 package.json 标记 1.2.9。旧 API 汇总中 project delete 的 GET、release detail 的双 ID 路径与 IL 不符，本次采用 IL。Creator 官方为 Bearer 认证，已有 Bearer 前缀不重复添加；主客户端发送存储 token 原样。修复后分别使用现有 Creator 与主客户端登录来源，各读取 Creator 项目列表和主客户端云备份列表，四次读取均被接受。这只记录这两套现有来源的读取结果。

配置分享 `content` 是公开富文本存储内容，图片替换成资源键标记；`contentText` 是公开纯文本。真实 detail 响应不返回 contentText；稀疏编辑会按官方 Q2 的 DOM textContent 规则从正文恢复，去除 WA/图片占位及脚本等隐藏节点，HTML 本身原样保留。明确更改正文而未给纯文本时，同步重新计算。WA 导入串由独立的 `codeText` 传输。官方编辑器保存时生成 HTML、存储 content、plainText 三份表示；读取兼容旧 Base64 内容，当前保存链没有再次 Base64 编码。IO 应按资源和字段语义区分公开正文与导入串。

本次已修复多处已有功能问题：Creator 发布文件的 metadata-only `md5` / `zip_size` / `unzip_size` 被丢弃和 `changelog:null` 被静默过滤；主客户端稀疏编辑重置 platform / excludeWtf / synchronizationType；读取 `--page` 没有映射实际页码；项目列表把 CLI envelope 参数带入请求。稀疏编辑现在先读当前 detail，再从允许字段重建完整提交体；创建默认值只用于新建。没有官方 null 清空证据的正文、角色等字段显式拒绝 null；订阅等级的 null 按官方完整表单省略 requiredTierId。

完成 project_state 现作为 license / publish_platforms 的规范来源：相同顶层值兼容，冲突在请求前拒绝；其他顶层元数据覆盖后重新执行状态机分类、平台、订阅等级和同步类型校验。

受限项目规则已补齐：`0 < project_id < 200000000` 的项目编辑先读取当前 detail，拒绝修改名称、仓库、平台、分类、订阅等级、依赖、许可证或图片，只提交官方允许的别名、简介、正文。删除项目和修改发布版本在 schema、dry-run、provider 均拒绝。

赛季订阅已接入 `GET /user/game-type/list` 和 `GET /user/author/season-sub/detail?authorId=...&gameType=...`；后者按官方设置不发 X-Server-Type。新增 `options subscription-game-types` 与 `options season-subscription --game-type <gameCode> [--author-id ID]`。选择赛季订阅时独立核对本人、当前游戏、ID、启用及结束状态。现有主客户端登录只读验证通过：游戏候选包含 wow_retail / wow_classic_titan，本人正式服当前无赛季候选，输出 null。

config / WA create 现已从 schema 移除编辑 ID，provider 同样明确拒绝。M-RESTRICTED、M-SEASON、M-CREATE-ID 均记录完成状态。作者订阅等级保存、Creator 二维码登录等平台能力尚无对应 CLI，继续在结构化审计中单列。

ModUs 五个 Build（0 至 4）均以仅合成内容完成生成、上传、改名、删除和读回，原有备份保留。正式服临时私密配置完成创建、长 HTML 编辑及图片/备份关联保留，2368 字符正文完整读回；关联备份在 confirm_delete=true 下拒删，先删配置再删备份后均确认消失。测试备份 4540、431、259、1557、443 及私密配置已清理。

实际接口验证发现 backup list 的请求分支头不足以证明返回行归属。预览按详情中的有效整数 serverType 过滤，错分支/缺失身份拒绝；删除扫描全部五个 Build 的分享分页及详情，跨分支关联也保护。DELETE 的 HTTP 5xx 或 2xx 坏 JSON 均报告结果不确定，不自动重放。关联补查必须核对请求身份。

### 只读命令与输入参数

| 命令 | 参数 | 默认/必填 |
| --- | --- | --- |
| `modus backup list` | `--server-type/--build` | 不传 |
| `modus backup get` | `--server-type/--build` | 不传 |
| `modus backup get` | `--backup-id` | 必填 |
| `modus backup scan` | `--server-type/--build` | 不传 |
| `modus backup scan` | `--game-root` | 必填 |
| `modus backup delete-preview` | `--server-type/--build` | 不传 |
| `modus backup delete-preview` | `--backup-ids` | 不传 |
| `modus backup delete-preview` | `--name-contains` | 不传 |
| `modus backup delete-preview` | `--name-equals` | 不传 |
| `modus backup delete-preview` | `--created-before` | 不传 |
| `modus backup delete-preview` | `--created-after` | 不传 |
| `modus session doctor` | `--client` | "creator"；可选 ["creator", "main"] |
| `modus builds` | 无额外参数 | — |
| `modus account info` | 无额外参数 | — |
| `modus account subscription-count` | 无额外参数 | — |
| `modus account statistics` | 无额外参数 | — |
| `modus addon info` | `--directory` | 必填 |
| `modus addon info` | `--server-type/--build` | 不传 |
| `modus addon project-info` | `--project-id` | 必填 |
| `modus addon project-info` | `--server-type/--build` | 不传 |
| `modus addon history` | `--project-id` | 必填 |
| `modus addon history` | `--server-type/--build` | 不传 |
| `modus addon history` | `--page` | 1 |
| `modus addon history` | `--page-size` | 50 |
| `modus options categories` | 无额外参数 | — |
| `modus options game-versions` | `--key` | 必填 |
| `modus options subscription-tiers` | 无额外参数 | — |
| `modus options subscription-game-types` | 无额外参数 | — |
| `modus options season-subscription` | `--game-type` | 必填 |
| `modus options season-subscription` | `--author-id` | 不传 |
| `modus options config-tags` | 无额外参数 | — |
| `modus options wa-tags` | 无额外参数 | — |
| `modus options wa-support-addons` | 无额外参数 | — |
| `modus project list` | `--keyword` | "" |
| `modus project list` | `--page` | 1 |
| `modus project list` | `--page-size` | 50 |
| `modus project get` | `--project-id` | 必填 |
| `modus project dependencies` | `--query` | 不传 |
| `modus project dependencies` | `--project-id` | 不传 |
| `modus plugin list` | `--project-id` | 必填 |
| `modus plugin list` | `--server-type/--build` | 不传 |
| `modus plugin list` | `--page` | 1 |
| `modus plugin list` | `--page-size` | 50 |
| `modus plugin get` | `--project-id` | 必填 |
| `modus plugin get` | `--file-id` | 必填 |
| `modus plugin get` | `--server-type/--build` | 不传 |
| `modus plugin versions` | `--project-id` | 必填 |
| `modus plugin versions` | `--server-type/--build` | 不传 |
| `modus plugin versions` | `--page` | 1 |
| `modus plugin versions` | `--page-size` | 50 |
| `modus config list` | `--server-type/--build` | 不传 |
| `modus config list` | `--page-num` | 不传 |
| `modus config list` | `--page-size` | 不传 |
| `modus config list` | `--keyword` | 不传 |
| `modus config list` | `--status` | 不传 |
| `modus config list` | `--share-type` | 不传 |
| `modus config list` | `--order-by` | 不传 |
| `modus config list` | `--mine/--no-mine` | 不传 |
| `modus config list` | `--is-public` | 不传；可选 [0, 1] |
| `modus config list` | `--is-paid` | 不传；可选 [0, 1] |
| `modus config list` | `--tags` | 不传 |
| `modus config get` | `--share-id` | 必填 |
| `modus config get` | `--server-type/--build` | 不传 |
| `modus config backups` | `--server-type/--build` | 不传 |
| `modus config backup-get` | `--backup-id` | 必填 |
| `modus config backup-get` | `--server-type/--build` | 不传 |
| `modus wa list` | `--server-type/--build` | 不传 |
| `modus wa list` | `--page-num` | 不传 |
| `modus wa list` | `--page-size` | 不传 |
| `modus wa list` | `--keyword` | 不传 |
| `modus wa list` | `--status` | 不传 |
| `modus wa list` | `--order-by` | 不传 |
| `modus wa list` | `--mine/--no-mine` | 不传 |
| `modus wa list` | `--support-addon` | 不传 |
| `modus wa list` | `--tags` | 不传 |
| `modus wa list` | `--is-paid` | 不传；可选 [0, 1] |
| `modus wa get` | `--import-id` | 必填 |
| `modus wa get` | `--server-type/--build` | 不传 |

<a id="modus-backup-create"></a>
### `backup create`

Schema：`fupload.v1.modus.backup.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_root` | `string` | 是 | 拒绝 | 非空 | 仅本机处理，不发接口：仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除；local-control；仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除 |
| `output_dir` | `string` | 是 | 拒绝 | 非空 | 仅本机处理，不发接口：仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除；local-control；仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除 |
| `backup_name` | `string` | 是 | 拒绝 | 非空；最多字符 80 | backupName；backup-name；generate写manifest；create/upload/register/rename使用相同名称 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | source.gameId / serverType / HTTP header.X-Server-Type；backup-context；generate写manifest；cloud注册写serverType；Build必须匹配manifest |
| `addon_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknownAddons(JSON string).list + ZIP；backup-selection；目录作为unknown addon保存实际文件；不猜project/file ID |
| `font_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | fonts(JSON string)[name,md5,size] + font object；backup-selection；先fontMd5存在性检查，按所选文件上传缺失字体 |
| `material_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | materialCosInfo(JSON string).list + ZIP；backup-selection；仅Interface下非AddOns所选材料 |
| `roles` | `array` | 否/条件必填 | 拒绝 | [{account,server,role}]; exact WTF role choices | wtfAccounts(JSON string).roles + WTF ZIP；backup-selection；账号/服务器/角色三元组；上传前校验层级并固定文件集，未选角色文件拒绝 |

字段映射依据：`['main_backup:SO', 'provider_backup:generate']`；`['main_backup:SO', 'provider_backup:upload']`；`['main_backup:oY/aY', 'provider_backup:_wtf_upload_plan']`；`['main_backup:rY', 'provider_backup:upload']`；`['provider_backup']`。

<a id="modus-backup-delete"></a>
### `backup delete`

Schema：`fupload.v1.modus.backup.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_ids` | `array` | 是 | 拒绝 | 非空；最多项 1000 | DELETE URL /system/user/backup/delete/{id}；protected-batch-delete；显式ID逐条全分页关联检查后删除；预览筛选不能直接写；有效serverType身份必需；检查全部五个Build的完整配置引用，不确定写入不重放。 |
| `confirm_delete` | `boolean` | 是 | 拒绝 | 可选 `[true]` | 仅本机处理，不发接口：本地确认，引用保护无确认绕过；local-control；本地确认，引用保护无确认绕过；有效serverType身份必需；检查全部五个Build的完整配置引用，不确定写入不重放。 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | source.gameId / serverType / HTTP header.X-Server-Type；backup-context；generate写manifest；cloud注册写serverType；Build必须匹配manifest；有效serverType身份必需；检查全部五个Build的完整配置引用，不确定写入不重放。 |

字段映射依据：`['main_backup:SO', 'provider_backup:upload']`；`['provider_backup']`；`['provider_backup:delete_many', 'provider_backup:references']`。

<a id="modus-backup-generate"></a>
### `backup generate`

Schema：`fupload.v1.modus.backup.generate`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `game_root` | `string` | 是 | 拒绝 | 非空 | 仅本机处理，不发接口：仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除；local-control；仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除 |
| `output_dir` | `string` | 是 | 拒绝 | 非空 | 仅本机处理，不发接口：仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除；local-control；仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除 |
| `backup_name` | `string` | 是 | 拒绝 | 非空；最多字符 80 | backupName；backup-name；generate写manifest；create/upload/register/rename使用相同名称 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | source.gameId / serverType / HTTP header.X-Server-Type；backup-context；generate写manifest；cloud注册写serverType；Build必须匹配manifest |
| `addon_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | unknownAddons(JSON string).list + ZIP；backup-selection；目录作为unknown addon保存实际文件；不猜project/file ID |
| `font_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | fonts(JSON string)[name,md5,size] + font object；backup-selection；先fontMd5存在性检查，按所选文件上传缺失字体 |
| `material_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | materialCosInfo(JSON string).list + ZIP；backup-selection；仅Interface下非AddOns所选材料 |
| `roles` | `array` | 否/条件必填 | 拒绝 | [{account,server,role}]; exact WTF role choices | wtfAccounts(JSON string).roles + WTF ZIP；backup-selection；账号/服务器/角色三元组；上传前校验层级并固定文件集，未选角色文件拒绝 |

字段映射依据：`['main_backup:SO', 'provider_backup:generate']`；`['main_backup:SO', 'provider_backup:upload']`；`['main_backup:oY/aY', 'provider_backup:_wtf_upload_plan']`；`['main_backup:rY', 'provider_backup:upload']`；`['provider_backup']`。

<a id="modus-backup-rename"></a>
### `backup rename`

Schema：`fupload.v1.modus.backup.rename`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_id` | `integer` | 是 | 拒绝 | 最小 1 | id；backup-rename；云数字ID；本地字符串backupId不能代用 |
| `backup_name` | `string` | 是 | 拒绝 | 非空；最多字符 80 | backupName；backup-name；generate写manifest；create/upload/register/rename使用相同名称 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | source.gameId / serverType / HTTP header.X-Server-Type；backup-context；generate写manifest；cloud注册写serverType；Build必须匹配manifest |

字段映射依据：`['main_backup:SO', 'provider_backup:generate']`；`['main_backup:SO', 'provider_backup:upload']`；`['provider_modus:cloud_backup_update']`。

<a id="modus-backup-upload"></a>
### `backup upload`

Schema：`fupload.v1.modus.backup.upload`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `manifest_file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | 仅本机处理，不发接口：仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除；local-control；仅本地选择/输出/读取manifest，不直接进入API；源路径从上传manifest递归移除 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | source.gameId / serverType / HTTP header.X-Server-Type；backup-context；generate写manifest；cloud注册写serverType；Build必须匹配manifest |

字段映射依据：`['main_backup:SO', 'provider_backup:upload']`；`['provider_backup']`。

<a id="modus-config-backup-delete"></a>
### `config backup-delete`

Schema：`fupload.v1.modus.config.backup-delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_id` | `integer` | 是 | 拒绝 | 最小 1 | URL id；cloud-backup-backup-delete；云端正整数ID，不能混用本地backupId |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | 仅本机处理，不发接口：只用于本地删除确认，不进入API body；local-control；只用于本地删除确认，不进入API body |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['main_api:L37390-L37515', 'provider_modus:_build']`；`['main_backup:backup endpoints', 'provider_modus:cloud_backup_update']`；`['provider_modus']`。

<a id="modus-config-backup-edit"></a>
### `config backup-edit`

Schema：`fupload.v1.modus.config.backup-edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `backup_id` | `integer` | 是 | 拒绝 | 最小 1 | id；cloud-backup-backup-edit；云端正整数ID，不能混用本地backupId |
| `backup_name` | `string` | 是 | 拒绝 | 非空；最多字符 200 | backupName；cloud-backup-rename；改名后detail读回 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['main_api:L37390-L37515', 'provider_modus:_build']`；`['main_backup:backup endpoints', 'provider_modus:cloud_backup_update']`；`['provider_modus:cloud_backup_update']`。

<a id="modus-config-create"></a>
### `config create`

Schema：`fupload.v1.modus.config.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `addons_id` | `string` | 是 | 拒绝 | 最多字符 10000 | addonsId；config-create；config来自backup knownAddons.projectids；WA来自适用插件选项；按字符串发送 |
| `account_name` | `string` | 否/条件必填 | 拒绝 | 最多字符 120 | accountName；config-create；字符串；null无明确官方清空语义现已在schema/provider拒绝；exclude_wtf=1时规范为空字符串 |
| `backup_id` | `integer` | 是 | 拒绝 | 最小 1 | backupId；config-create；云正整数ID；改ID须显式给addon/WTF账号/角色选择 |
| `content` | `string` | 是 | 拒绝 | 非空 | content；config-create；公开富文本存储HTML；图片可为资源键标记，可能包含编辑器WA块；不能当原始配置串整体摘要 |
| `content_text` | `string` | 是 | 拒绝 | 非空 | contentText；config-create；公开正文纯文本，不是HTML也不是配置码；用于长度校验/检索；真实detail省略contentText时按官方Q2从正文恢复；正文改动且未指定纯文本时同步重算。 |
| `image_url` | `string` | 是 | 拒绝 | 非空；最多字符 1000 | imageUrl；config-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `is_paid` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPaid；config-create；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `is_public` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPublic；config-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `price` | `number` | 否/条件必填 | 拒绝 | 最小 0 | price；config-create；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `share_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | shareType；config-create；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `tags` | `string` | 是 | 拒绝 | 非空；最多字符 1000 | tags；config-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `title` | `string` | 是 | 拒绝 | 非空；最多字符 120 | title；config-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `exclude_wtf` | `integer` | 是 | 拒绝 | 可选 `[0, 1]` | excludeWtf；config-create；0/1；1排除WTF并清空accountName/roleName；更新未提供时保留原值 |
| `role_name` | `string` | 否/条件必填 | 拒绝 | 最多字符 120 | roleName；config-create；字符串；null无明确官方清空语义现已在schema/provider拒绝；exclude_wtf=1时规范为空字符串 |
| `required_tier_id` | `integer` | 否/条件必填 | 允许 | 最小 1 | requiredTierId；config-create；null=官方无档位；创建省略，完整更新表单删除旧requiredTierId键。sub_type=0校验普通tiers；sub_type=1读取本人当前gameCode的season detail，只接受相同id、isEnabled=1且platformSeasonStatus!=2。稀疏编辑取当前subType/requiredTierId补齐后校验。 |
| `sub_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | subType；config-create；normal=0/season=1；官方season档位由独立season detail API读取，Fupload尚无该发现命令 |
| `platform` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | platform；config-create；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `synchronization_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | synchronizationType；config-create；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['config_form:L314-L363', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire', 'main_api:L10823-L10828', 'main_api:L11014-L11019', 'provider_modus:author_season_subscription/_validate_main_write']`；`['config_form:L314-L363', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire']`；`['main_api:L37390-L37515', 'provider_modus:_build']`。

<a id="modus-config-delete"></a>
### `config delete`

Schema：`fupload.v1.modus.config.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `share_id` | `identifier` | 是 | 拒绝 | 非空 | URL opaque id；config-delete；ID按不透明字符串URL编码；不转float/Number |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | 仅本机处理，不发接口：只用于本地删除确认，不进入API body；local-control；只用于本地删除确认，不进入API body |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['config_form:L314-L363', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire']`；`['main_api:L37390-L37515', 'provider_modus:_build']`；`['provider_modus']`。

<a id="modus-config-edit"></a>
### `config edit`

Schema：`fupload.v1.modus.config.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `share_id` | `identifier` | 是 | 拒绝 | 非空 | id；config-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `addons_id` | `string` | 否/条件必填 | 拒绝 | 最多字符 10000 | addonsId；config-edit；config来自backup knownAddons.projectids；WA来自适用插件选项；按字符串发送 |
| `account_name` | `string` | 否/条件必填 | 拒绝 | 最多字符 120 | accountName；config-edit；字符串；null无明确官方清空语义现已在schema/provider拒绝；exclude_wtf=1时规范为空字符串 |
| `backup_id` | `integer` | 否/条件必填 | 拒绝 | 最小 1 | backupId；config-edit；云正整数ID；改ID须显式给addon/WTF账号/角色选择 |
| `content` | `string` | 否/条件必填 | 拒绝 | 非空 | content；config-edit；公开富文本存储HTML；图片可为资源键标记，可能包含编辑器WA块；不能当原始配置串整体摘要 |
| `content_text` | `string` | 否/条件必填 | 拒绝 | 非空 | contentText；config-edit；公开正文纯文本，不是HTML也不是配置码；用于长度校验/检索；真实detail省略contentText时按官方Q2从正文恢复；正文改动且未指定纯文本时同步重算。 |
| `image_url` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | imageUrl；config-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `is_paid` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPaid；config-edit；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `is_public` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPublic；config-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `price` | `number` | 否/条件必填 | 拒绝 | 最小 0 | price；config-edit；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `share_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | shareType；config-edit；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `tags` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | tags；config-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `title` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | title；config-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `exclude_wtf` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | excludeWtf；config-edit；0/1；1排除WTF并清空accountName/roleName；更新未提供时保留原值 |
| `role_name` | `string` | 否/条件必填 | 拒绝 | 最多字符 120 | roleName；config-edit；字符串；null无明确官方清空语义现已在schema/provider拒绝；exclude_wtf=1时规范为空字符串 |
| `required_tier_id` | `integer` | 否/条件必填 | 允许 | 最小 1 | requiredTierId；config-edit；null=官方无档位；创建省略，完整更新表单删除旧requiredTierId键。sub_type=0校验普通tiers；sub_type=1读取本人当前gameCode的season detail，只接受相同id、isEnabled=1且platformSeasonStatus!=2。稀疏编辑取当前subType/requiredTierId补齐后校验。 |
| `sub_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | subType；config-edit；normal=0/season=1；官方season档位由独立season detail API读取，Fupload尚无该发现命令 |
| `platform` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | platform；config-edit；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `synchronization_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | synchronizationType；config-edit；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['config_form:L314-L363', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire', 'main_api:L10823-L10828', 'main_api:L11014-L11019', 'provider_modus:author_season_subscription/_validate_main_write']`；`['config_form:L314-L363', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire']`；`['main_api:L37390-L37515', 'provider_modus:_build']`。

<a id="modus-config-update"></a>
### `config update`

Schema：`fupload.v1.modus.config.update`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `share_id` | `identifier` | 是 | 拒绝 | 非空 | id；config-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `addons_id` | `string` | 否/条件必填 | 拒绝 | 最多字符 10000 | addonsId；config-update；config来自backup knownAddons.projectids；WA来自适用插件选项；按字符串发送 |
| `account_name` | `string` | 否/条件必填 | 拒绝 | 最多字符 120 | accountName；config-update；字符串；null无明确官方清空语义现已在schema/provider拒绝；exclude_wtf=1时规范为空字符串 |
| `backup_id` | `integer` | 否/条件必填 | 拒绝 | 最小 1 | backupId；config-update；云正整数ID；改ID须显式给addon/WTF账号/角色选择 |
| `content` | `string` | 否/条件必填 | 拒绝 | 非空 | content；config-update；公开富文本存储HTML；图片可为资源键标记，可能包含编辑器WA块；不能当原始配置串整体摘要 |
| `content_text` | `string` | 否/条件必填 | 拒绝 | 非空 | contentText；config-update；公开正文纯文本，不是HTML也不是配置码；用于长度校验/检索；真实detail省略contentText时按官方Q2从正文恢复；正文改动且未指定纯文本时同步重算。 |
| `image_url` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | imageUrl；config-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `is_paid` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPaid；config-update；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `is_public` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPublic；config-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `price` | `number` | 否/条件必填 | 拒绝 | 最小 0 | price；config-update；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `share_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | shareType；config-update；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `tags` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | tags；config-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `title` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | title；config-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `exclude_wtf` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | excludeWtf；config-update；0/1；1排除WTF并清空accountName/roleName；更新未提供时保留原值 |
| `role_name` | `string` | 否/条件必填 | 拒绝 | 最多字符 120 | roleName；config-update；字符串；null无明确官方清空语义现已在schema/provider拒绝；exclude_wtf=1时规范为空字符串 |
| `required_tier_id` | `integer` | 否/条件必填 | 允许 | 最小 1 | requiredTierId；config-update；null=官方无档位；创建省略，完整更新表单删除旧requiredTierId键。sub_type=0校验普通tiers；sub_type=1读取本人当前gameCode的season detail，只接受相同id、isEnabled=1且platformSeasonStatus!=2。稀疏编辑取当前subType/requiredTierId补齐后校验。 |
| `sub_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | subType；config-update；normal=0/season=1；官方season档位由独立season detail API读取，Fupload尚无该发现命令 |
| `platform` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | platform；config-update；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `synchronization_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | synchronizationType；config-update；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['config_form:L314-L363', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire', 'main_api:L10823-L10828', 'main_api:L11014-L11019', 'provider_modus:author_season_subscription/_validate_main_write']`；`['config_form:L314-L363', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire']`；`['main_api:L37390-L37515', 'provider_modus:_build']`。

<a id="modus-media-upload"></a>
### `media upload`

Schema：`fupload.v1.modus.media.upload`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | multipart.file；image-upload；main图片原文件，返回对象key；无X-Server-Type |

字段映射依据：`['config_form:image upload helper', 'provider_modus:image_upload']`。

<a id="modus-plugin-create"></a>
### `plugin create`

Schema：`fupload.v1.modus.plugin.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `project_id` | `integer` | 是 | 拒绝 | 最小 1 | projectId；release-create；按字段存在发送；省略保留；官方受限项目0<id<200000000禁止该写入，schema/dry-run/执行均拒绝 |
| `file_id` | `integer` | 否/条件必填 | 拒绝 | 最小 1 | fileId；release-create；create/upload只用于签名与对象路径；metadata create不发fileId；update/edit发fileId |
| `version` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | version；release-create；按字段存在发送；省略保留 |
| `type` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 40 | type；release-create；按字段存在发送；省略保留 |
| `supported_game_versions` | `array` | 否/条件必填 | 拒绝 | 非空 | supportedGameVersionsReqs；release-create；数组元素严格为gameVersion/server；ZIP时必须与Interface及wow_builds实时选项一致 |
| `md5` | `string` | 否/条件必填 | 拒绝 | 最多字符 64 | md5；release-create；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `zip_size` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | zipSize；release-create；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `unzip_size` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | unzipSize；release-create；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `path` | `string` | 否/条件必填 | 拒绝 | 最多字符 500 | path；release-create；按字段存在发送；省略保留 |
| `toc_version` | `string` | 否/条件必填 | 拒绝 | 最多字符 80 | tocVersion；release-create；按字段存在发送；省略保留 |
| `changelog` | `string` | 否/条件必填 | 允许 | 最多字符 10000 | changelog；release-create；编辑显式null发送JSON null清空（官方OptionalStringUpdate）；创建空值不表示清旧记录 |
| `file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | PUT ZIP bytes；binary-upload；本地ZIP；metadata与对象上传分开；缺file的edit/update没有PUT |
| `transaction_log` | `string` | 否/条件必填 | 拒绝 | 最多字符 1000 | 仅本机处理，不发接口：仅本地事务记录路径；不进入API body；local-control；仅本地事务记录路径；不进入API body |

字段映射依据：`['creator_api:L16568-L16690', 'creator_api:L17632-L17725', 'provider_modus:_release_wire', 'provider_modus:publish']`；`['creator_api:UploadReleasePackageAsync', 'provider_modus:publish']`；`['provider_modus']`。

<a id="modus-plugin-delete"></a>
### `plugin delete`

Schema：`fupload.v1.modus.plugin.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `project_id` | `integer` | 是 | 拒绝 | 最小 1 | projectId；release-delete；POST delete body仅projectId/fileId；官方受限项目0<id<200000000禁止该写入，schema/dry-run/执行均拒绝 |
| `file_id` | `integer` | 是 | 拒绝 | 最小 1 | fileId；release-delete；POST delete body仅projectId/fileId |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | 仅本机处理，不发接口：删除本地确认，不进入HTTP body；local-control；删除本地确认，不进入HTTP body |

字段映射依据：`['creator_api:L16568-L16690', 'creator_api:L17632-L17725', 'provider_modus:_release_wire', 'provider_modus:publish']`；`['provider_modus']`。

<a id="modus-plugin-edit"></a>
### `plugin edit`

Schema：`fupload.v1.modus.plugin.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `project_id` | `integer` | 是 | 拒绝 | 最小 1 | projectId；release-edit；按字段存在发送；省略保留；官方受限项目0<id<200000000禁止该写入，schema/dry-run/执行均拒绝 |
| `file_id` | `integer` | 是 | 拒绝 | 最小 1 | fileId；release-edit；create/upload只用于签名与对象路径；metadata create不发fileId；update/edit发fileId |
| `version` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | version；release-edit；按字段存在发送；省略保留 |
| `type` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 40 | type；release-edit；按字段存在发送；省略保留 |
| `supported_game_versions` | `array` | 否/条件必填 | 拒绝 | 非空 | supportedGameVersionsReqs；release-edit；数组元素严格为gameVersion/server；ZIP时必须与Interface及wow_builds实时选项一致 |
| `md5` | `string` | 否/条件必填 | 拒绝 | 最多字符 64 | md5；release-edit；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `zip_size` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | zipSize；release-edit；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `unzip_size` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | unzipSize；release-edit；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `path` | `string` | 否/条件必填 | 拒绝 | 最多字符 500 | path；release-edit；按字段存在发送；省略保留 |
| `toc_version` | `string` | 否/条件必填 | 拒绝 | 最多字符 80 | tocVersion；release-edit；按字段存在发送；省略保留 |
| `changelog` | `string` | 否/条件必填 | 允许 | 最多字符 10000 | changelog；release-edit；编辑显式null发送JSON null清空（官方OptionalStringUpdate）；创建空值不表示清旧记录 |
| `file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | PUT ZIP bytes；binary-upload；本地ZIP；metadata与对象上传分开；缺file的edit/update没有PUT |
| `transaction_log` | `string` | 否/条件必填 | 拒绝 | 最多字符 1000 | 仅本机处理，不发接口：仅本地事务记录路径；不进入API body；local-control；仅本地事务记录路径；不进入API body |

字段映射依据：`['creator_api:L16568-L16690', 'creator_api:L17632-L17725', 'provider_modus:_release_wire', 'provider_modus:publish']`；`['creator_api:UploadReleasePackageAsync', 'provider_modus:publish']`；`['provider_modus']`。

<a id="modus-plugin-update"></a>
### `plugin update`

Schema：`fupload.v1.modus.plugin.update`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `project_id` | `integer` | 是 | 拒绝 | 最小 1 | projectId；release-update；按字段存在发送；省略保留；官方受限项目0<id<200000000禁止该写入，schema/dry-run/执行均拒绝 |
| `file_id` | `integer` | 是 | 拒绝 | 最小 1 | fileId；release-update；create/upload只用于签名与对象路径；metadata create不发fileId；update/edit发fileId |
| `version` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | version；release-update；按字段存在发送；省略保留 |
| `type` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 40 | type；release-update；按字段存在发送；省略保留 |
| `supported_game_versions` | `array` | 否/条件必填 | 拒绝 | 非空 | supportedGameVersionsReqs；release-update；数组元素严格为gameVersion/server；ZIP时必须与Interface及wow_builds实时选项一致 |
| `md5` | `string` | 否/条件必填 | 拒绝 | 最多字符 64 | md5；release-update；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `zip_size` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | zipSize；release-update；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `unzip_size` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | unzipSize；release-update；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `path` | `string` | 否/条件必填 | 拒绝 | 最多字符 500 | path；release-update；按字段存在发送；省略保留 |
| `toc_version` | `string` | 否/条件必填 | 拒绝 | 最多字符 80 | tocVersion；release-update；按字段存在发送；省略保留 |
| `changelog` | `string` | 否/条件必填 | 允许 | 最多字符 10000 | changelog；release-update；编辑显式null发送JSON null清空（官方OptionalStringUpdate）；创建空值不表示清旧记录 |
| `file` | `string` | 否/条件必填 | 拒绝 | 本机存在的普通文件 | PUT ZIP bytes；binary-upload；本地ZIP；metadata与对象上传分开；缺file的edit/update没有PUT |
| `transaction_log` | `string` | 否/条件必填 | 拒绝 | 最多字符 1000 | 仅本机处理，不发接口：仅本地事务记录路径；不进入API body；local-control；仅本地事务记录路径；不进入API body |

字段映射依据：`['creator_api:L16568-L16690', 'creator_api:L17632-L17725', 'provider_modus:_release_wire', 'provider_modus:publish']`；`['creator_api:UploadReleasePackageAsync', 'provider_modus:publish']`；`['provider_modus']`。

<a id="modus-plugin-upload"></a>
### `plugin upload`

Schema：`fupload.v1.modus.plugin.upload`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `project_id` | `integer` | 是 | 拒绝 | 最小 1 | projectId；release-upload；按字段存在发送；省略保留；官方受限项目0<id<200000000禁止该写入，schema/dry-run/执行均拒绝 |
| `file_id` | `integer` | 否/条件必填 | 拒绝 | 最小 1 | fileId；release-upload；create/upload只用于签名与对象路径；metadata create不发fileId；update/edit发fileId |
| `version` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | version；release-upload；按字段存在发送；省略保留 |
| `type` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 40 | type；release-upload；按字段存在发送；省略保留 |
| `supported_game_versions` | `array` | 否/条件必填 | 拒绝 | 非空 | supportedGameVersionsReqs；release-upload；数组元素严格为gameVersion/server；ZIP时必须与Interface及wow_builds实时选项一致 |
| `md5` | `string` | 否/条件必填 | 拒绝 | 最多字符 64 | md5；release-upload；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `zip_size` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | zipSize；release-upload；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `unzip_size` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | unzipSize；release-upload；有ZIP则派生并校验显式值；无ZIP的update/edit透传显式metadata（本轮修复原忽略输入） |
| `path` | `string` | 否/条件必填 | 拒绝 | 最多字符 500 | path；release-upload；按字段存在发送；省略保留 |
| `toc_version` | `string` | 否/条件必填 | 拒绝 | 最多字符 80 | tocVersion；release-upload；按字段存在发送；省略保留 |
| `changelog` | `string` | 否/条件必填 | 允许 | 最多字符 10000 | changelog；release-upload；编辑显式null发送JSON null清空（官方OptionalStringUpdate）；创建空值不表示清旧记录 |
| `file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | PUT ZIP bytes；binary-upload；本地ZIP；metadata与对象上传分开；缺file的edit/update没有PUT |
| `transaction_log` | `string` | 否/条件必填 | 拒绝 | 最多字符 1000 | 仅本机处理，不发接口：仅本地事务记录路径；不进入API body；local-control；仅本地事务记录路径；不进入API body |

字段映射依据：`['creator_api:L16568-L16690', 'creator_api:L17632-L17725', 'provider_modus:_release_wire', 'provider_modus:publish']`；`['creator_api:UploadReleasePackageAsync', 'provider_modus:publish']`；`['provider_modus']`。

<a id="modus-project-create"></a>
### `project create`

Schema：`fupload.v1.modus.project.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | name；project-create；项目名；编辑由显式值覆盖state basic_info同名值 |
| `alt_name` | `string` | 否/条件必填 | 拒绝 | 最多字符 120 | altName；project-create；创建可空；编辑空字符串转换官方<null>标记 |
| `summary` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 500 | summary；project-create；编辑空值官方使用<null>；当前schema要求非空字符串 |
| `categories` | `array` | 否/条件必填 | 拒绝 | 非空；最多项 5 | categories；project-create；官方CSV分类ID；998仅BigFoot；分类来源options categories |
| `license` | `object` | 否/条件必填 | 拒绝 | 非空 | license(JSON string)；project-create；有效来源是project_state.license；当前顶层license被snapshot覆盖，冲突输入会静默无效 |
| `repo_url` | `string` | 否/条件必填 | 拒绝 | 最多字符 500 | repoUrl；project-create；创建空白时省略；编辑空字符串转换<null> |
| `required_tier_id` | `integer` | 否/条件必填 | 允许 | 最小 1 | requiredTierId；project-create；创建正整数；编辑数字字符串或<null>清空 |
| `publish_platforms` | `array` | 否/条件必填 | 拒绝 | 非空 | synchronizationType（由state.basic_info派生）；project-create；modus=1,bigfoot=2,两者=3；当前顶层publish_platforms不重新派生sync，冲突时被snapshot派生值盖过 |
| `project_state` | `object` | 是 | 拒绝 | 非空 | 仅本机处理，不发接口：complete状态快照；game/basic_info/license先本地恢复校验，状态/游戏UI对象不直接送API；业务字段投影到官方payload；local-control；complete状态快照；game/basic_info/license先本地恢复校验，状态/游戏UI对象不直接送API；业务字段投影到官方payload |
| `logo_base64` | `string` | 否/条件必填 | 拒绝 | 非空 | screenshotBase64sReqs.screenshotBase64s；project-create；创建logo.webp的WebP Base64字符串 |
| `screenshot_base64s` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | screenshotBase64sReqs.screenshotBase64s；project-create；创建兼容输入：仅在缺logo_base64时取数组第一个元素；不是多图截图上传 |

字段映射依据：`['creator_api:L8561-L8685', 'provider_modus:_project_wire']`；`['creator_vm:L654-L676', 'provider_modus:_project_document']`；`['provider_modus']`；`['provider_modus:_project_document', 'creator_api:BuildLicenseJson']`。

<a id="modus-project-delete"></a>
### `project delete`

Schema：`fupload.v1.modus.project.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `project_id` | `integer` | 是 | 拒绝 | 最小 1 | URL projectId；project-delete；正整数；delete实际为POST；官方受限项目0<id<200000000禁止该写入，schema/dry-run/执行均拒绝 |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | 仅本机处理，不发接口：本地DELETE确认，不进入HTTP body；local-control；本地DELETE确认，不进入HTTP body |

字段映射依据：`['creator_api:L9210-L9240', 'provider_modus:project_delete']`；`['provider_modus']`。

<a id="modus-project-edit"></a>
### `project edit`

Schema：`fupload.v1.modus.project.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `project_id` | `integer` | 是 | 拒绝 | 非空 | projectId；project-edit；正整数；delete实际为POST |
| `name` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | name；project-edit；项目名；编辑由显式值覆盖state basic_info同名值 |
| `alt_name` | `string` | 否/条件必填 | 拒绝 | 最多字符 120 | altName；project-edit；创建可空；编辑空字符串转换官方<null>标记 |
| `summary` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 500 | summary；project-edit；编辑空值官方使用<null>；当前schema要求非空字符串 |
| `categories` | `array` | 否/条件必填 | 拒绝 | 非空；最多项 5 | categories；project-edit；官方CSV分类ID；998仅BigFoot；分类来源options categories |
| `license` | `object` | 否/条件必填 | 拒绝 | 非空 | license(JSON string)；project-edit；有效来源是project_state.license；当前顶层license被snapshot覆盖，冲突输入会静默无效 |
| `repo_url` | `string` | 否/条件必填 | 拒绝 | 最多字符 500 | repoUrl；project-edit；创建空白时省略；编辑空字符串转换<null> |
| `required_tier_id` | `integer` | 否/条件必填 | 允许 | 最小 1 | requiredTierId；project-edit；创建正整数；编辑数字字符串或<null>清空 |
| `publish_platforms` | `array` | 否/条件必填 | 拒绝 | 非空 | synchronizationType（由state.basic_info派生）；project-edit；modus=1,bigfoot=2,两者=3；当前顶层publish_platforms不重新派生sync，冲突时被snapshot派生值盖过 |
| `project_state` | `object` | 是 | 拒绝 | 非空 | 仅本机处理，不发接口：complete状态快照；game/basic_info/license先本地恢复校验，状态/游戏UI对象不直接送API；业务字段投影到官方payload；local-control；complete状态快照；game/basic_info/license先本地恢复校验，状态/游戏UI对象不直接送API；业务字段投影到官方payload |
| `description` | `string` | 否/条件必填 | 允许 | 最多字符 100000 | description；project-edit；仅编辑；保持存储HTML，清空为<null> |
| `required_dependencies` | `string` | 否/条件必填 | 允许 | 最多字符 4000 | requiredDependencies；project-edit；仅编辑；依赖项目ID CSV，空值为<null> |
| `images` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | images；project-edit；编辑imagesOps时必须同时给出最终图片数量 |
| `image_ops` | `array` | 否/条件必填 | 拒绝 | 非空 | imagesOps；project-edit；编辑upload/delete/rename操作，保持官方name/from/to/base64字段 |

字段映射依据：`['creator_api:L9210-L9240', 'provider_modus:_project_wire']`；`['creator_vm:BuildProjectChanges', 'provider_modus:_project_wire']`；`['creator_vm:L654-L676', 'provider_modus:_project_document']`；`['provider_modus']`；`['provider_modus:_project_document', 'creator_api:BuildLicenseJson']`。

<a id="modus-wa-create"></a>
### `wa create`

Schema：`fupload.v1.modus.wa.create`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `code_text` | `string` | 是 | 拒绝 | 非空 | codeText；wa-create；WA/import原始导入字符串，输出仍需保护；与公开Article正文区分 |
| `content` | `string` | 是 | 拒绝 | 非空 | content；wa-create；公开富文本存储HTML；图片可为资源键标记，可能包含编辑器WA块；不能当原始配置串整体摘要 |
| `addons_id` | `string` | 是 | 拒绝 | 非空；最多字符 10000 | addonsId；wa-create；config来自backup knownAddons.projectids；WA来自适用插件选项；按字符串发送 |
| `content_text` | `string` | 是 | 拒绝 | 非空 | contentText；wa-create；公开正文纯文本，不是HTML也不是配置码；用于长度校验/检索；真实detail省略contentText时按官方Q2从正文恢复；正文改动且未指定纯文本时同步重算。 |
| `file_path` | `string` | 否/条件必填 | 拒绝 | 可选 `[""]` | filePath；wa-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `image_url` | `string` | 是 | 拒绝 | 非空；最多字符 1000 | imageUrl；wa-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `is_paid` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPaid；wa-create；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `is_public` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPublic；wa-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `price` | `number` | 否/条件必填 | 拒绝 | 最小 0 | price；wa-create；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `share_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | shareType；wa-create；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `support_addon` | `string` | 是 | 拒绝 | 非空；最多字符 120 | supportAddon；wa-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `tags` | `string` | 是 | 拒绝 | 非空；最多字符 1000 | tags；wa-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `title` | `string` | 是 | 拒绝 | 非空；最多字符 120 | title；wa-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `version` | `string` | 是 | 拒绝 | 非空；最多字符 120 | version；wa-create；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `required_tier_id` | `integer` | 否/条件必填 | 允许 | 最小 1 | requiredTierId；wa-create；null=官方无档位；创建省略，完整更新表单删除旧requiredTierId键。sub_type=0校验普通tiers；sub_type=1读取本人当前gameCode的season detail，只接受相同id、isEnabled=1且platformSeasonStatus!=2。稀疏编辑取当前subType/requiredTierId补齐后校验。 |
| `sub_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | subType；wa-create；normal=0/season=1；官方season档位由独立season detail API读取，Fupload尚无该发现命令 |
| `platform` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | platform；wa-create；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `synchronization_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | synchronizationType；wa-create；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['main_api:L37390-L37515', 'provider_modus:_build']`；`['wa_form:L432-L465', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire', 'main_api:L10823-L10828', 'main_api:L11014-L11019', 'provider_modus:author_season_subscription/_validate_main_write']`；`['wa_form:L432-L465', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire']`。

<a id="modus-wa-delete"></a>
### `wa delete`

Schema：`fupload.v1.modus.wa.delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `import_id` | `identifier` | 是 | 拒绝 | 非空 | URL opaque id；wa-delete；ID按不透明字符串URL编码；不转float/Number |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | 仅本机处理，不发接口：只用于本地删除确认，不进入API body；local-control；只用于本地删除确认，不进入API body |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['main_api:L37390-L37515', 'provider_modus:_build']`；`['provider_modus']`；`['wa_form:L432-L465', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire']`。

<a id="modus-wa-edit"></a>
### `wa edit`

Schema：`fupload.v1.modus.wa.edit`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `import_id` | `identifier` | 是 | 拒绝 | 非空 | id；wa-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `code_text` | `string` | 否/条件必填 | 拒绝 | 非空 | codeText；wa-edit；WA/import原始导入字符串，输出仍需保护；与公开Article正文区分 |
| `content` | `string` | 否/条件必填 | 拒绝 | 非空 | content；wa-edit；公开富文本存储HTML；图片可为资源键标记，可能包含编辑器WA块；不能当原始配置串整体摘要 |
| `addons_id` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 10000 | addonsId；wa-edit；config来自backup knownAddons.projectids；WA来自适用插件选项；按字符串发送 |
| `content_text` | `string` | 否/条件必填 | 拒绝 | 非空 | contentText；wa-edit；公开正文纯文本，不是HTML也不是配置码；用于长度校验/检索；真实detail省略contentText时按官方Q2从正文恢复；正文改动且未指定纯文本时同步重算。 |
| `file_path` | `string` | 否/条件必填 | 拒绝 | 可选 `[""]` | filePath；wa-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `image_url` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | imageUrl；wa-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `is_paid` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPaid；wa-edit；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `is_public` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPublic；wa-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `price` | `number` | 否/条件必填 | 拒绝 | 最小 0 | price；wa-edit；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `share_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | shareType；wa-edit；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `support_addon` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | supportAddon；wa-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `tags` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | tags；wa-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `title` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | title；wa-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `version` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | version；wa-edit；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `required_tier_id` | `integer` | 否/条件必填 | 允许 | 最小 1 | requiredTierId；wa-edit；null=官方无档位；创建省略，完整更新表单删除旧requiredTierId键。sub_type=0校验普通tiers；sub_type=1读取本人当前gameCode的season detail，只接受相同id、isEnabled=1且platformSeasonStatus!=2。稀疏编辑取当前subType/requiredTierId补齐后校验。 |
| `sub_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | subType；wa-edit；normal=0/season=1；官方season档位由独立season detail API读取，Fupload尚无该发现命令 |
| `platform` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | platform；wa-edit；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `synchronization_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | synchronizationType；wa-edit；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['main_api:L37390-L37515', 'provider_modus:_build']`；`['wa_form:L432-L465', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire', 'main_api:L10823-L10828', 'main_api:L11014-L11019', 'provider_modus:author_season_subscription/_validate_main_write']`；`['wa_form:L432-L465', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire']`。

<a id="modus-wa-update"></a>
### `wa update`

Schema：`fupload.v1.modus.wa.update`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `import_id` | `identifier` | 是 | 拒绝 | 非空 | id；wa-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `code_text` | `string` | 否/条件必填 | 拒绝 | 非空 | codeText；wa-update；WA/import原始导入字符串，输出仍需保护；与公开Article正文区分 |
| `content` | `string` | 否/条件必填 | 拒绝 | 非空 | content；wa-update；公开富文本存储HTML；图片可为资源键标记，可能包含编辑器WA块；不能当原始配置串整体摘要 |
| `addons_id` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 10000 | addonsId；wa-update；config来自backup knownAddons.projectids；WA来自适用插件选项；按字符串发送 |
| `content_text` | `string` | 否/条件必填 | 拒绝 | 非空 | contentText；wa-update；公开正文纯文本，不是HTML也不是配置码；用于长度校验/检索；真实detail省略contentText时按官方Q2从正文恢复；正文改动且未指定纯文本时同步重算。 |
| `file_path` | `string` | 否/条件必填 | 拒绝 | 可选 `[""]` | filePath；wa-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `image_url` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | imageUrl；wa-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `is_paid` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPaid；wa-update；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `is_public` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | isPublic；wa-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `price` | `number` | 否/条件必填 | 拒绝 | 最小 0 | price；wa-update；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `share_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0 | shareType；wa-update；所审官方表单固定免费0；schema不应把其它服务端值描述成已支持业务分支 |
| `support_addon` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | supportAddon；wa-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `tags` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 1000 | tags；wa-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `title` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | title；wa-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `version` | `string` | 否/条件必填 | 拒绝 | 非空；最多字符 120 | version；wa-update；创建按显式字段；edit/update先完整detail再allowlist保留省略字段 |
| `required_tier_id` | `integer` | 否/条件必填 | 允许 | 最小 1 | requiredTierId；wa-update；null=官方无档位；创建省略，完整更新表单删除旧requiredTierId键。sub_type=0校验普通tiers；sub_type=1读取本人当前gameCode的season detail，只接受相同id、isEnabled=1且platformSeasonStatus!=2。稀疏编辑取当前subType/requiredTierId补齐后校验。 |
| `sub_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[0, 1]` | subType；wa-update；normal=0/season=1；官方season档位由独立season detail API读取，Fupload尚无该发现命令 |
| `platform` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | platform；wa-update；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `synchronization_type` | `integer` | 否/条件必填 | 拒绝 | 可选 `[1, 3]` | synchronizationType；wa-update；已实现wire转发及本地1/3约束；本次所审1.2.9编辑器payload未包含此选择，不能据schema声称当前UI完整展示 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['main_api:L37390-L37515', 'provider_modus:_build']`；`['wa_form:L432-L465', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire', 'main_api:L10823-L10828', 'main_api:L11014-L11019', 'provider_modus:author_season_subscription/_validate_main_write']`；`['wa_form:L432-L465', 'subscription_form:buildSubscriptionPayload', 'provider_modus:_main_update_wire']`。

<a id="modus-wa-version-delete"></a>
### `wa version-delete`

Schema：`fupload.v1.modus.wa.version-delete`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `version_id` | `identifier` | 是 | 拒绝 | 非空 | query.versionId；import-version-delete；不放body；DELETE |
| `confirm` | `string` | 是 | 拒绝 | 可选 `["DELETE"]` | 仅本机处理，不发接口：只用于本地删除确认，不进入API body；local-control；只用于本地删除确认，不进入API body |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['main_api:L37390-L37515', 'provider_modus:_build']`；`['main_api:L37500-L37512', 'provider_modus:import_version_delete']`；`['provider_modus']`。

<a id="modus-wa-version-publish"></a>
### `wa version-publish`

Schema：`fupload.v1.modus.wa.version-publish`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `import_id` | `identifier` | 是 | 拒绝 | 非空 | importId；import-version-publish；changelog为空白时省略；单次发布新不可变版本 |
| `version` | `string` | 是 | 拒绝 | 非空；最多字符 120 | version；import-version-publish；changelog为空白时省略；单次发布新不可变版本 |
| `code_text` | `string` | 是 | 拒绝 | 非空 | codeText；import-version-publish；changelog为空白时省略；单次发布新不可变版本 |
| `changelog` | `string` | 否/条件必填 | 拒绝 | 最多字符 10000 | changelog；import-version-publish；changelog为空白时省略；单次发布新不可变版本 |
| `server_type` | `integer` | 否/条件必填 | 拒绝 | 最小 0；最大 4 | HTTP header.X-Server-Type；request-context；0-4，0有效；不进入写body |

字段映射依据：`['main_api:L37390-L37515', 'provider_modus:_build']`；`['main_api:L37490-L37499', 'provider_modus:import_version_publish']`。

### 补充嵌套或协议字段

以下不是额外的顶层 JSON 字段；是否可由用户填写，以对应对象结构和动作说明为准。

| 字段路径 | 接口字段/用途 | 条件 | 依据 |
| --- | --- | --- | --- |
| `options.season-subscription.author_id` | GET query authorId | 可选正整数；省略从当前登录userInfo取userId/id，不接受token输入 | `['subscription_form:GET_AUTHOR_SEASON_SUB_DETAIL', 'provider_modus:author_season_subscription']` |
| `options.season-subscription.game_type` | GET query gameType | CLI必填官方gameCode，由subscription-game-types读取；写入校验用当前server_type关联官方gameCode | `['main_api:L10828', 'main_api:L11006-L11019', 'subscription_form', 'provider_modus:author_season_subscription']` |
| `project.*.project_state.basic_info.alt_name` | altName | 创建可空；编辑空字符串转换官方<null>标记 | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.categories` | categories | 官方CSV分类ID；998仅BigFoot；分类来源options categories | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.cf_url` | 仅本机处理，不发接口：可保存原detail投影；当前_project_wire不发送该服务端字段 | 可保存原detail投影；当前_project_wire不发送该服务端字段 | `['provider_modus']` |
| `project.*.project_state.basic_info.description` | description | 仅编辑；保持存储HTML，清空为<null> | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.image_ops` | imagesOps | 编辑upload/delete/rename操作，保持官方name/from/to/base64字段 | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.images` | images | 编辑imagesOps时必须同时给出最终图片数量 | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.logo` | 仅本机处理，不发接口：可保存原detail投影；当前_project_wire不发送该服务端字段 | 可保存原detail投影；当前_project_wire不发送该服务端字段 | `['provider_modus']` |
| `project.*.project_state.basic_info.logo_base64` | screenshotBase64sReqs.screenshotBase64s | 创建logo.webp的WebP Base64字符串 | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.name` | name | 项目名；编辑由显式值覆盖state basic_info同名值 | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.publish_platforms` | synchronizationType | 位掩码1/2/3；998为BigFoot独占；有BigFoot不能选普通tier | `['creator_vm:L654-L676', 'provider_modus:ProjectStateMachine']` |
| `project.*.project_state.basic_info.repo_url` | repoUrl | 创建空白时省略；编辑空字符串转换<null> | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.required_dependencies` | requiredDependencies | 仅编辑；依赖项目ID CSV，空值为<null> | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.required_tier_id` | requiredTierId | 创建正整数；编辑数字字符串或<null>清空 | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.screenshot_base64s` | screenshotBase64sReqs.screenshotBase64s | 创建兼容输入：仅在缺logo_base64时取数组第一个元素；不是多图截图上传 | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.basic_info.status` | 仅本机处理，不发接口：可保存原detail投影；当前_project_wire不发送该服务端字段 | 可保存原detail投影；当前_project_wire不发送该服务端字段 | `['provider_modus']` |
| `project.*.project_state.basic_info.summary` | summary | 编辑空值官方使用<null>；当前schema要求非空字符串 | `['creator_vm:ProjectCreate/Create and BuildProjectChanges', 'provider_modus:_project_document']` |
| `project.*.project_state.game` | 仅本机处理，不发接口：游戏选择只在本地步骤与读回模型中保存；官方CreateProject payload没有game字段 | 游戏选择只在本地步骤与读回模型中保存；官方CreateProject payload没有game字段 | `['provider_modus']` |
| `project.*.project_state.license.content` | license(JSON string).content | snapshot license为有效来源，官方JSON字符串只加入非空属性 | `['creator_api:BuildLicenseJson', 'provider_modus:_license_json']` |
| `project.*.project_state.license.holder` | license(JSON string).holder | snapshot license为有效来源，官方JSON字符串只加入非空属性 | `['creator_api:BuildLicenseJson', 'provider_modus:_license_json']` |
| `project.*.project_state.license.type` | license(JSON string).type | snapshot license为有效来源，官方JSON字符串只加入非空属性 | `['creator_api:BuildLicenseJson', 'provider_modus:_license_json']` |
| `project.*.project_state.license.year` | license(JSON string).year | snapshot license为有效来源，官方JSON字符串只加入非空属性 | `['creator_api:BuildLicenseJson', 'provider_modus:_license_json']` |

<a id="curseforge"></a>
## CurseForge

[官方上传 API 文档](https://support.curseforge.com/support/solutions/articles/9000197321)说明 multipart 元数据、发布版本和依赖关系字段；[Core REST 官方文档](https://docs.curseforge.com/rest-api/)说明搜索分页与作者筛选。Core 的 authorId 筛选项目成员，primaryAuthorId 才筛选主要作者。现有作者项目列表使用前者。

作者列表原本只获取首 50 项，现已逐页读取，并检查稳定总数、页码、返回计数、重复 ID 和提前空页；达到官方 10000 索引边界而未完成时明确报错，不返回完整假象。缺少总数的响应继续读取至空页。

平台已有 `POST /api/projects/{projectId}/update-file` 修改文件元数据能力，Fupload 本次没有增加该写入动作。依赖项发现和 Core 文件详情 / changelog 查询也仅列为平台能力缺口。上传接口返回文件 ID 表示服务器接受，不代表审核或后续处理完成；当前工具没有相应状态读回。

### 只读命令与输入参数

| 命令 | 参数 | 默认/必填 |
| --- | --- | --- |
| `curseforge session doctor` | 无额外参数 | — |
| `curseforge project list` | `--author-id` | 不传 |
| `curseforge plugin game-versions` | 无额外参数 | — |

<a id="curseforge-plugin-upload"></a>
### `plugin upload`

Schema：`fupload.v1.curseforge.plugin.upload`。

| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |
| --- | --- | --- | --- | --- | --- |
| `project_id` | `integer` | 是 | 拒绝 | 最小 1 | URL /api/projects/{projectId}/upload-file；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `file` | `string` | 是 | 拒绝 | 本机存在的普通文件 | multipart.file；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `changelog` | `string` | 是 | 拒绝 | 见动作条件及嵌套结构 | multipart.metadata(JSON).changelog；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `changelog_type` | `string` | 否/条件必填 | 拒绝 | 可选 `["text", "html", "markdown"]` | multipart.metadata(JSON).changelogType；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `display_name` | `string` | 否/条件必填 | 拒绝 | 非空 | multipart.metadata(JSON).displayName；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `game_versions` | `array` | 否/条件必填 | 拒绝 | 非空 | multipart.metadata(JSON).gameVersions；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `game_version_names` | `array` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | multipart.metadata(JSON).gameVersionNames；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `release_type` | `string` | 是 | 拒绝 | 可选 `["alpha", "beta", "release"]` | multipart.metadata(JSON).releaseType；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `parent_file_id` | `integer` | 否/条件必填 | 拒绝 | 最小 1 | multipart.metadata(JSON).parentFileID；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `relations` | `object` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | multipart.metadata(JSON).relations.projects；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |
| `is_marked_for_manual_release` | `boolean` | 否/条件必填 | 拒绝 | 见动作条件及嵌套结构 | multipart.metadata(JSON).isMarkedForManualRelease；file-upload；父文件模式不发送两个版本字段；上传返回ID不等于已审核/公开 |

字段映射依据：`['cf_upload:L74-L102', 'provider_cf:CurseForge.upload']`。

### 补充嵌套或协议字段

以下不是额外的顶层 JSON 字段；是否可由用户填写，以对应对象结构和动作说明为准。

| 字段路径 | 接口字段/用途 | 条件 | 依据 |
| --- | --- | --- | --- |
| `plugin.upload.relations.projects[].project_id` | metadata.relations.projects[].projectID | 可选精确关联ID | `['cf_upload:L88-L96', 'provider_cf:upload']` |
| `plugin.upload.relations.projects[].slug` | metadata.relations.projects[].slug | 关联项目slug | `['cf_upload:L88-L96', 'provider_cf:upload']` |
| `plugin.upload.relations.projects[].type` | metadata.relations.projects[].type | 官方关联枚举；不推测其它取值 | `['cf_upload:L88-L96', 'provider_cf:upload']` |

## 覆盖检查

已列出 88 个 Schema 的全部字段。尚待核对的协议映射：0 个动作字段位置。
