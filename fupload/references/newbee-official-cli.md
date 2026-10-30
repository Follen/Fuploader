# NewBeeBox 官方 CLI 参考（ncc 0.1.29）

核对日期：2026-10-30。以下正文来自本机 `ncc docs`；入口文档：https://creator.newbeebox.com/md/cli-docs。安装版本变化时以新的 `ncc docs` 和命令 `--help` 为准。

Fupload 不读取官方 CLI 凭据文件。官方通道与 Python 第三方通道的字段、登录及能力差异见 [平台字段总表](platform-fields.md#newbee)。

# ncc —— 新手盒子创作者中心 CLI 使用教程与规范

版本: 0.1.29

ncc 是创作者中心的命令行客户端，用于在本地终端管理和发布创作内容。
当前支持魔兽世界插件、字符串、配置分享与社区帖子的发布与维护，更多内容类型将陆续接入。

魔兽相关命令在 ncc wow 下（addons 插件 / wa 字符串 / uipack 配置分享 / media 媒体 / cloudbackup 云端备份），社区相关命令在 ncc community 下。

## 快速上手

1. 前往创作者中心「CLI 令牌」页创建令牌（明文仅创建时展示一次；直接运行 ncc login 会自动打开该页）
2. ncc login --token ncc_xxx
3. cd 你的插件目录
4. ncc wow addons init --id <mod_id>        # 首次关联插件（ID 用 ncc wow addons list 查询）
5. ncc wow addons push --dry-run            # 预检：校验参数并试打包，不上传
6. ncc wow addons push --changelog "修复了..."   # 正式上传

首次创建一个新插件（而非关联已有）：ncc wow addons create --name ... --categories ... --logo ... --screenshots ...，创建后再 init 关联本地目录、push 上传插件文件。

## 使用规范

1. **输出格式**：默认输出人类可读文本（精简中文视图：枚举转文本并按状态着色、时间戳转本地时区、列表附分页指引；管道/重定向或设置 NO_COLOR 时自动无色）；脚本/自动化调用请加 `-o json`，stdout 输出规范化字段的稳定 JSON（字段名语义化，枚举同时含数值与 *_text 中文文本；成功是数据、失败是 {error, message, hint}），stderr 只有提示信息，解析 stdout 即可。
2. **非交互**：参数齐全时零提问。参数缺失会直接以结构化错误退出，错误里写明缺什么、可选值、建议值——按提示补参即可，不要原样重试。
3. **退出码**：0 成功 / 1 业务错误 / 2 鉴权失败（需重新 ncc login）/ 3 网络错误（可重试）。
4. **认证**：优先使用环境变量 NCC_TOKEN（CI/脚本免落盘）；或 ncc login 写入 ~/.ncc/config.json。令牌失效时请在创作者中心重新创建。
5. **限额**：上传有每日/每分钟次数限制，失败不要循环重试；quota_exceeded / cli_disabled 一律停止并改用创作者中心网页操作。

## 命令参考

ncc login --token ncc_xxx        登录（免交互）
ncc logout                       登出
ncc whoami                       当前创作者身份/令牌信息/模块权限
ncc config                       查看本地配置（令牌脱敏）
ncc docs                         输出本教程
ncc completion <shell>           输出 tab 补全脚本（bash|zsh|powershell），如 ncc completion bash >> ~/.bashrc 后重开终端生效

ncc wow addons list [page] [--keyword <kw>] [--pagesize N]
    我的插件列表（查询插件 ID）；--keyword 按名称/描述搜索；翻页直接 ncc wow addons list 2，列表尾部有分页摘要与下一页命令
ncc wow addons info <mod_id>
    插件详情：审核/发布状态、当前信息（简介/描述/分类/图标/截图/官网，长文本完整值用 -o json 取）、最新版本与下载链接
ncc wow addons create --name <n> --description <text|@file> --categories <ids> --logo <file|url> --screenshots <items> [--intro <t>] [--home-page <n> --home-page-link <url>] [--private] [--origin original|repost|localized] [--subscribe-level N] [--link-channel]
    创建一个新插件（图标/截图可传本地图片路径自动上传或已上传链接）。创建成功返回插件 ID；随后 init 关联本地目录、push 上传插件文件。删除插件只能在创作者中心网页端操作。
ncc wow addons edit <mod_id> [--name <n>] [--description <text|@file>] [--intro <t>] [--categories <ids>] [--logo <file|url>] [--screenshots <items>] [--private|--public] [--subscribe-level N] [--link-channel]
    编辑已发布插件的信息：只改传入项，其余字段保持不变，不会误清空。改动公开内容会重新进入审核。删除插件只能在网页端操作。
ncc wow addons categories [--refresh-config]
    插件分类表（创建插件时用 ID 选择分类）
ncc wow addons init [dir] --id <mod_id>
    生成 ncc.json 关联插件（自动回填最近一次上传的适配版本）。一个目录只能 init 一次，已初始化会报错 already_initialized。
    目录三态：插件目录（自带 .toc）或整合包父目录（子目录各自带 .toc）→ 直接关联；
    空目录或不存在的目录 → 自动拉取该插件线上最新版本落地为完整工程：插件代码 + ncc.json + 描述正文 description.md
    （编辑后 addons edit --description @description.md 回写；要求线上已有上传版本）；
    其余目录 → 报错 toc_not_found，不会关联到错误目录。
    已初始化的工程要把本地内容追平线上最新版本，用 ncc wow addons sync（见下）。
ncc wow addons push [dir] [--version <v>] [--changelog <text|@file>] [--game-versions <spec>] [--dry-run]
    打包目录并上传新版本（核心命令）
ncc wow addons pack [dir] [--version <v>] [--out <path>]
    纯离线打包为本地 zip，不上传、无需登录（文件名 <目录名>-<版本号>.zip，版本号缺省读 ncc.json）
ncc wow addons sync [dir] --yes
    用线上最新版本整体覆盖本地工程内容（插件 ID 读 ncc.json，无需传参）——线上被网页端/其他机器更新后本地追平用。
    可替换区与打包收录范围一致：打包会进包的内容文件全部以线上为准替换（本地多出来的也会删除）；
    打包忽略的一律保留（ncc.json、隐藏文件、ignore 规则命中的素材源、整合包顶层散文件）。
    覆盖后找不回来，须附 --yes 确认；同步完成后 ncc.json 的 game_versions 自动回填线上最新组合。
    bundle 多模块工程暂不支持 sync。
ncc wow addons versions --id <mod_id> [page] [--pagesize N]
    版本文件列表（查询 file_id），按上传时间倒序；翻页直接在命令尾部加页码，列表尾部有分页摘要与下一页命令
ncc wow addons changelog <file_id> [--set <text|@file>]
    查看/编辑版本更新日志
ncc wow addons comments list <mod_id> [page] [--unreplied|--replied]
    某个插件收到的评价列表，含评分/点赞/热门回复；--unreplied 只看未回复的
ncc wow addons comments reply <review_id> --content <text|@file>
    回复一条插件评价（评价 ID 从列表获取），回复先进平台审核后公开

ncc wow wa list [page] [--keyword <kw>] [--paid|--free]
    我的字符串列表（查询字符串 ID）；--keyword 按名称/简介搜索；翻页直接 ncc wow wa list 2
ncc wow wa info <wa_id>
    字符串详情：审核/公开状态、当前信息（简介/描述/分类/图片）、字符串模式与版本
ncc wow wa publish --name <n> --description <text|@file> --wa-str <text|@file> --game-version <id|名称> --categories <ids> --thumbnail <file|url> [--images <items>] [--changelog <t>] [--intro <t>] [--private] [--price <元>] [--subscribe-level N] [--time-range <r>] [--origin ...] [--link-channel]
    发布一条字符串（单字符串形态）。分类 ID 用 ncc wow wa categories --game-version X 查询；付费内容进入人工审核。多字符串与附件走网页端。删除只能在网页端操作。
ncc wow wa edit <wa_id> [--name <n>] [--description <text|@file>] [--intro <t>] [--categories <ids>] [--thumbnail <file|url>] [--images <items>] [--private|--public] [--price <元>] [--subscribe-level N] [--link-channel]
    编辑已发布字符串的信息：只改传入项，其余字段（含价格/付费有效期/可见性）保持不变，不指定不会归零或清空。改动付费/公开内容会重新进入审核。多字符串请用网页端；字符串内容更新走 ncc wow wa push。
ncc wow wa categories --game-version <id|名称> [--refresh-config]
    字符串分类表（按游戏版本查询，发布时用 ID 选择分类）
ncc wow wa init [dir] --id <wa_id>
    把线上字符串完整落地为本地工程（只支持空目录或不存在的目录）：字符串内容 wa_<ID>_v<版本>.txt
    + 描述正文 description.md（wa edit --description @description.md 回写）+ project.json（名称/简介/版本/适配版本/价格/可见性快照）
ncc wow wa pull <wa_id> [--out <path>]
    拉取字符串内容保存到本地文件（默认 wa_<ID>_v<版本>.txt），用于本地编辑与备份
ncc wow wa push <wa_id> --file <path> --log <text|@file> [--version <v>]
    推送本地文件为字符串新版本。更新日志必填；--version 须为 1.2.3 形式且大于当前版本，缺省自动递增修订号。
    多字符串模式的字符串仅支持 pull，push 会被拒绝——请在创作者中心网页端更新，避免破坏字符串结构。
ncc wow wa comments list <wa_id> [page] [--unreplied|--replied]
    某条字符串收到的评价列表；--unreplied 只看未回复的
ncc wow wa comments reply <review_id> --content <text|@file>
    回复一条字符串评价，回复先进平台审核后公开

ncc wow uipack list [page] [--keyword <kw>] [--paid|--free]
    我的配置分享列表（查询配置 ID）；--keyword 按分享码/标题搜索
ncc wow uipack info <config_id>
    配置分享详情：审核/公开状态、来源云端备份与分享角色、摘要与正文格式（正文全文用 pull 拉取）。
    注意：-o json 时配置分享的 visibility 编码为 0=私密/1=公开（与插件/字符串的 2=私密/1=公开 不同），text 模式已统一显示中文状态。
ncc wow uipack publish --backup <backup_id> --title <t> --content <text|@file> --images <items> [--role <id>] [--intro <t>] [--private] [--price <元>] [--subscribe-level N] [--time-range <r>] [--origin ...] [--link-channel]
    基于云端备份发布配置分享（备份 ID 用 ncc wow cloudbackup list 查询）。插件关联与忽略清单从备份构成自动推导（与网页端全选插件的效果一致）。
    备份包含 WTF 角色配置时必须用 --role 选定一个分享角色（角色数据 ID 用 ncc wow cloudbackup info 查询；漏传时错误信息会列出全部可选角色）。
    公开发布需认证作者。删除只能在网页端操作。
ncc wow uipack init [dir] --id <config_id>
    把线上配置分享完整落地为本地工程（只支持空目录或不存在的目录）：正文 uipack_<ID>.md
    + project.json（标题/摘要/可见性 + 所基于的云端备份信息 + 选中的 WTF 分享角色[账号-服务器-角色]快照）
ncc wow uipack pull <config_id> [--out <path>]
    拉取正文内容保存到本地文件（默认 uipack_<ID>.md），用于本地编辑与备份
ncc wow uipack push <config_id> [--file <path>] [--title <text>] [--intro <text|@file>]
    更新文本内容，至少传一项：--file 正文（Markdown）、--title 标题、--intro 摘要（缺省且更新了正文时自动从正文提取）。
    正文更新仅支持 Markdown 格式的配置分享，HTML 富文本存量请在创作者中心网页端编辑。
    配置分享的版本更新依赖游戏内数据，请通过盒子客户端完成；CLI 负责文字内容维护与基于备份的发布。
ncc wow uipack comments list <config_id> [page] [--unreplied|--replied]
    某个配置分享收到的评价列表；--unreplied 只看未回复的
ncc wow uipack comments reply <review_id> --content <text|@file>
    回复一条配置分享评价，回复先进平台审核后公开

ncc wow media upload <file> --for uipack|addons|wa
    上传本地图片取得平台链接（用于配置分享/插件/字符串的正文嵌图与图标/截图/展示图）。
    支持图片 png/jpg/jpeg/gif/webp/bmp/ico 与视频 mp4；图片上传即进平台内容审查，违规直接拒绝。
    社区帖子正文的图片用 ncc community media upload。

ncc wow cloudbackup list
    云端备份历史记录（按备份时间倒序），含每个备份的内容构成计数、被引用的配置分享数与账户槽位使用
ncc wow cloudbackup info <backup_id>
    单个备份基础信息：插件构成清单（已知插件/未知插件/字体/材质）、游戏账号与角色配置结构（角色附带角色数据 ID，发布配置分享 --role 用它）、被引用的配置分享。
    云端备份为只读信息，备份的上传与恢复请通过盒子客户端完成。

ncc wow ref <addons|wa|uipack> <id> [--link] [--game-version <id|名称>]
    生成正文内联引用代码（默认卡片形态，--link 换链接形态），把输出的引用代码原样粘进正文即可，发布后渲染为对应卡片/链接。
    只能引用自己名下的内容；--game-version 仅 addons 有效，按游戏版本引用。详见「正文内联引用」一节。

ncc community post list [page] [--keyword <kw>] [--private|--public]
    我的社区帖子列表（查询帖子 ID 与状态）
ncc community post info <post_id>
    帖子详情：正文/话题/状态与计数，以及附件清单（附件序号供 download / detach 引用）
ncc community post init [dir] --id <post_id>
    把线上帖子完整落地为本地工程（只支持空目录）：正文文件 post_<ID>.md（HTML 存量为 .html）
    + 全部附件下载到 attachments/ 目录 + project.json（标题/摘要/话题/类型/可见性与附件清单快照）；
    正文编辑后 post edit 回写，附件调整用 attach / detach，附件重新拉取用 download
ncc community post pull <post_id> [--out <path>]
    拉取帖子正文保存到本地文件（默认 post_<ID>.md），用于本地编辑与备份；
    编辑后用 ncc community post edit <post_id> --content @文件 回写（仅 Markdown 帖可回写，HTML 存量仅备份）
ncc community post publish --content <text|@file> [--title <t>] [--intro <t>] [--topics a,b] [--type dynamic|guide|help] [--private]
    发布纯文本帖子（Markdown，需已开通频道）；发布后可用 attach 挂附件，引用等富内容走网页端
ncc community post edit <post_id> [--title <t>] [--content <text|@file>] [--intro <t>] [--public|--private]
    编辑帖子文本与可见性（至少一项）；正文仅 Markdown 帖可编辑，HTML 富文本存量走网页端
ncc community post delete <post_id> --yes
    删除帖子（不可恢复，必须附 --yes 确认）
ncc community post attach <post_id> <file...>
    上传本地文件并追加为帖子附件（流程见「帖子附件管理」一节）
ncc community post detach <post_id> --index <n> --yes
    移除帖子附件（序号从 info 查看；只解除挂载关系，须附 --yes 确认）
ncc community post download <post_id> [--index <n>|--all] [--out <dir>]
    下载帖子附件到本地（只有一个附件时可省略 --index）
ncc community post comments [page] [--post <id>] [--unreplied|--replied] [--keyword <kw>]
    我的帖子收到的评论（跨帖聚合），含未回复计数与我的回复标记
ncc community post comment-reply <comment_id> --content <text|@file>
    回复一条帖子评论（自动@被回复用户）
ncc community post comment-delete <comment_id> --yes
    删除帖子评论（自己帖子下的任意评论；一级评论连带其回复，必须附 --yes 确认）
ncc community media upload <file>
    上传本地图片取得平台链接（用于帖子正文 Markdown 嵌图）

全局参数: -o json|text（默认 text）/ -c 紧凑JSON / --token

## 正文嵌图流程（配置分享 / 社区帖子）

正文是 Markdown 纯文本，图片不随 push/publish 一起上传——先把本地图片换成平台链接，再嵌入正文：

1. ncc wow media upload screenshot.png --for uipack   # 上传图片（社区帖子用 ncc community media upload），返回链接与 Markdown 引用
2. 把返回的 `![](https://...)` 粘贴到本地正文文件的目标位置
3. ncc wow uipack push 55 --file uipack_55.md         # 推送正文（社区帖子对应 ncc community post publish / edit）

- 图片在上传时即进平台内容审查，违规图片直接拒绝、不产生链接；正文推送时的文本审查不再重复审图。
- 请使用本流程返回的平台链接嵌图，站外图床外链不保证正常展示。
- 上传计入每日上传限额；同一张图复用链接即可，无需重复上传。

## 正文内联引用（配置分享 / 社区帖子）

正文里可以嵌入对自己其他作品的引用，展示为卡片或链接（与创作者中心编辑器的「插入引用」一致）：

1. ncc wow ref uipack 58789                 # 生成配置分享 58789 的引用代码（--link 换链接形态）
2. 把返回的 `{[shareConfig=-=58789=-=标题=-=1]}` 原样粘进本地正文文件的目标位置
3. ncc wow uipack push 55 --file uipack_55.md   # 推送正文（社区帖子对应 ncc community post publish / edit）

- 支持引用自己名下的插件（addons）/字符串（wa）/配置分享（uipack）；他人内容与站外内容不可引用。
- 插件引用可加 --game-version 指定游戏版本（ID 或名称），缺省不区分版本。
- uipack pull 与 community post info 会解析正文中已有的引用并列出「正文内引用」清单，便于核对。
- 引用代码是整体标记，请勿手工改动其中的分隔符与 ID。

## 帖子附件管理（社区帖子）

附件是挂在帖子上的可下载文件（区别于正文嵌图）：文件本体走盒子网盘直传直取，
帖子只记录附件清单。附件功能依赖随 CLI 安装的传输组件（仅 Windows/macOS 可用）。

1. ncc community post attach 88 整合包.zip 说明.png   # 上传文件并追加为 88 号帖子的附件（可多个）
2. ncc community post info 88                          # 查看附件清单与序号
3. ncc community post download 88 --index 1 --out ./dl # 按序号下载（--all 全部下载）
4. ncc community post detach 88 --index 2 --yes        # 移除附件（只解除挂载关系）

- 支持图片 png/jpg/jpeg/gif/webp/bmp/ico、视频 mp4 与压缩包 zip/rar/7z/tar/gz，每帖最多 10 个。
- 大文件自动分块并发传输并带进度显示；同一文件重复上传会秒传。
- 若提示传输组件未安装（nbbcore_missing），按错误提示中的命令补装后重试。

## push 的参数取值规则

- 版本名 version: --version > ncc.json 的 version 字段 > 报错。报错时附 latest_version（当前最新版本名）与 suggested_version（可解析时的 patch 自增建议）。版本名是自由文本，同插件内不可重复。
- 适配客户端版本 --game-versions 两种写法:
  1. 显式版本串: 11.2.7,12.1.0（必须在平台支持列表内）
  2. auto: 从目录 .toc 的 "## Interface:" 自动检测
  只关联插件实际适配的当前客户端版本，不支持按游戏版本整组选择（整组含大量历史客户端版本）。
  未指定时读 ncc.json 的 game_versions；都没有则报错并附各游戏版本可选的客户端版本清单。
- changelog: --changelog 直接给文本，或 @CHANGELOG.md 从文件读；未指定时若 ncc.json 配置了 changelog_file 且文件存在则自动读取。
- 打包: 自动识别目录形态——单体插件（目录自己带 .toc）内容包在目录名文件夹下，与手动压缩插件文件夹一致；整合包（目录下多个插件文件夹、各自带 .toc）子文件夹直接作为压缩包顶层，与整合包发布形态一致，且顶层散文件（与 ncc.json 同层的 README、CHANGELOG.md 等）一律不进包——压缩包顶层只有插件文件夹，配置类文件放在插件文件夹那一层最干净。默认排除 .git/.ncc/ncc.json/隐藏文件/*.zip/addon_version.txt（平台安装插件时写入的版本标记文件，进包会污染版本识别）+ ncc.json 的 ignore 规则 + 打包根目录的 .nccignore（无则回落读 .gitignore，与 npm 发包约定一致；支持 # 注释，不支持 ! 反排除；不含 / 的模式在任意层级匹配）；上限 2048MB。pack 与 push 打包行为一致，pack 仅落地本地 zip 不上传。整合包无需任何额外配置，init/push 用法与单体完全相同。工程直接放在游戏 AddOns 目录、一个产品由主插件+多个兄弟模块组成的形态，用 ncc.json 的 bundle 字段显式声明，见「多模块打包 bundle」一节。

## ncc.json 配置说明

{
  "game": "wow",
  "type": "mod",
  "id": 123,                      // 插件 ID
  "name": "MyAddon",              // 插件名（仅展示用）
  "version": "2.0.4",             // 下次 push 的版本名（也可用 --version 传入）
  "game_versions": ["12.1.0"],    // 适配客户端版本（显式版本串，init 自动回填）
  "changelog_file": "CHANGELOG.md",  // push 时自动读取的日志文件（可选）
  "ignore": ["*.psd", "node_modules/**"],  // 打包排除规则（可选）
  "bundle": ["MyAddon_Options"]   // 附属模块目录名清单（可选，多模块形态用，见下节）
}

排除规则也可写在打包根目录的 .nccignore 文件里（一行一条，无 .nccignore 时自动读 .gitignore，
与 npm 发包约定一致），与 ncc.json 的 ignore 数组取并集。

init 只支持一次：已有 ncc.json 的目录再次 init 会报错 already_initialized——更换关联插件直接编辑
ncc.json 的 id 字段，确要重新生成先删除 ncc.json。init 时会检查目录结构：插件目录（自带 .toc）或
整合包父目录（子目录各自带 .toc）直接关联；空目录（或不存在的目录）自动拉取线上最新版本落地为
标准工程（zip 顶层插件文件夹 → 目录子文件夹，与打包互为逆运算，落地后直接可 push）；
其余目录报错 toc_not_found，避免在错误目录关联后 push 时才失败。

## 多模块打包 bundle（工程在游戏目录、主插件+附属模块形态）

一个产品由主插件和多个附属模块组成、且各模块直接散在游戏 AddOns 目录同层时
（如 MyAddon + MyAddon_Options + MyAddon_Config），在主插件目录的 ncc.json 里声明 bundle：

{
  "id": 123,
  "bundle": ["MyAddon_Options", "MyAddon_Config"]
}

打包规则（供人与自动化工具共同遵守的完整规则集）：

1. **成员**：主插件目录（ncc.json 所在目录）无条件进包，不写进 bundle（写了视为冗余忽略）；
   bundle 项只接受主插件同层的目录名，不接受路径（含 / 或 \ 直接报错 manifest_invalid）；重复项去重。
2. **校验**：主插件目录与每个附属模块目录都必须自带 .toc，否则报错 manifest_invalid；
   附属模块目录不存在同样报错。独立工程整合包（模块在工程子目录下）不要用 bundle，走自动检测。
3. **布局**：每个模块在 zip 内以自己的目录名作顶层文件夹（MyAddon/** MyAddon_Options/**），
   与整合包发布形态一致；bundle 模式没有顶层散文件概念（各模块目录即插件文件夹）。
4. **适配版本**：--game-versions auto 时聚合主插件与全部附属模块 .toc 的 Interface 声明（并集去重）。
5. **排除规则两层，全部是黑名单、取并集、无优先级冲突**：
   - 产品级：主插件 ncc.json 的 ignore 数组，作用于全部模块；
   - 模块级：每个模块目录（含主插件自己）各自的 .nccignore（无则回落该目录的 .gitignore），只作用于该模块自身。
   两层的匹配基准都是模块内相对路径（不含模块名前缀）：不含 / 的模式在任意层级匹配，
   含 / 的模式从该模块根目录锚定；内置默认排除（.git/.ncc/ncc.json/隐藏文件/*.zip/addon_version.txt）在每个模块内同样生效。
6. **兼容**：bundle 缺省或为空数组时行为与旧版本完全一致（单体/整合包自动检测），零破坏。

## 错误码枚举（-o json 时 stdout 的 error 字段）

auth_failed             令牌无效/未登录 → 重新创建令牌并 ncc login
network_error           网络故障 → 可重试
missing_version         缺版本名 → 参考 extra.suggested_version
version_exists          版本名重复 → 参考 extra.suggested_version 换一个
missing_game_versions   缺适配版本 → 参考 extra.groups 选择
invalid_game_version    版本写法不识别 → 从 extra.groups 选择显式版本串
toc_not_found           目录里没找到 .toc（init 结构检查 / --game-versions auto 检测失败）→ 确认目录 / 改用显式版本串
already_initialized     目录已有 ncc.json → 更换关联直接编辑 id 字段, 重新生成先删 ncc.json
file_too_large          zip 超 2048MB → 用 ignore 规则排除大文件
write_failed            本地文件写入失败 → 确认输出目录存在且有写权限
file_not_found          @file / --file 指定的文件读取失败 → 确认文件路径
invalid_param           参数值不合法（读 message 与 hint）
need_confirm            删除/覆盖类操作需要 --yes 确认（读 hint）
nbbcore_missing         附件传输组件未安装/加载失败 → 按 hint 中的命令补装
upload_failed           附件上传网盘失败 → 可重试，多次失败检查网络
download_failed         附件下载失败 → 可重试，多次失败检查网络
quota_exceeded          触发平台限额 → 次日再试或走网页端
cli_version_outdated    CLI 版本过低被拦截 → npm i -g @newbeebox/newbeebox-creator-center-cli@latest 升级
cli_disabled            平台临时关闭 CLI → 走网页端
cli_not_authorized      CLI 功能内测中, 当前账号未开通 → 走网页端
mod_not_found           插件不存在或不属于当前用户
invalid_usage           命令用法错误（缺参数/未知选项等）→ 在命令后加 --help 查看用法
manifest_invalid        ncc.json 损坏
api_error               其他服务端业务错误（读 message）

## 常见问题

- 看不到创作者中心的「CLI 令牌」入口？CLI 功能内测中, 仅部分创作者开放, 后续将逐步全量。
- 上传后看不到新版本？付费插件需人工审核通过后对外可见。
- 令牌忘了？令牌明文仅创建时展示一次，丢失请吊销后重新创建。
- 提示版本过低？运行 npm i -g @newbeebox/newbeebox-creator-center-cli@latest 升级到最新版。
