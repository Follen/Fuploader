<!--
Source: https://creator.newbeebox.com/md/cli-docs
Retrieved: 2026-07-31
Runtime rule: the installed `ncc docs` and leaf `--help` take precedence for execution.
The official document below is preserved in full.
-->

# 新手盒子 创作者中心 CLI（ncc）

> 本文件是机器可读版本，供脚本与自动化工具直接抓取（GET /md/cli-docs，UTF-8 纯文本）。
> 网页版：/cli-docs ；终端内查看：`ncc docs`（内容一致）。

在本地终端管理和发布创作内容。当前支持魔兽世界插件、字符串、配置分享与社区帖子的发布与维护，更多内容类型将陆续接入。魔兽相关命令在 `ncc wow` 下，社区相关命令在 `ncc community` 下。

## 安装

### 第一步：准备 Node.js（已安装可跳过）

要求 Node.js >= 18。终端运行 `node -v`，能输出 v18 以上版本号即已就绪；未安装时：

- Windows：终端运行 `winget install OpenJS.NodeJS.LTS`，或到 https://nodejs.org/zh-cn/download 下载 LTS 安装包
- macOS：`brew install node`，或官网下载安装包
- Linux：用发行版包管理器安装 nodejs，或使用 nvm

### 第二步：安装 CLI

```
npm i -g @newbeebox/newbeebox-creator-center-cli@latest
```

可选：开启 tab 补全 —— PowerShell 运行 `ncc completion powershell >> $PROFILE`（bash / zsh 对应 `ncc completion bash >> ~/.bashrc`、`ncc completion zsh >> ~/.zshrc`），重开终端生效。

### AI 助手一键安装

习惯用 AI 助手 / 本地模型的话，把下面的提示词复制给它（令牌在「CLI 令牌」页创建后替换进去），由它代劳完成安装配置：

```
请帮我在本机安装并配置「新手盒子 创作者中心 CLI」，按顺序执行，每步失败时停下来说明原因：
1. 运行 node -v 检查 Node.js，未安装或版本低于 18 时先安装 Node.js LTS（Windows: winget install OpenJS.NodeJS.LTS；macOS: brew install node；或从 https://nodejs.org 下载安装）
2. 运行 npm i -g @newbeebox/newbeebox-creator-center-cli@latest 安装 CLI
3. 运行 ncc -V 和 ncc --help 验证安装成功
4. 运行 ncc login --token <替换成你的ncc_令牌> 登录，再运行 ncc whoami 验证身份
5. 运行 ncc docs 获取完整使用文档，按文档用 ncc wow addons init 把我的插件目录关联好
```

## 快速上手

1. 前往创作者中心「CLI 令牌」页（/creator-center/cli-token）创建令牌（明文仅创建时展示一次，请立即保存）
2. 登录并关联插件目录：

```
ncc login --token ncc_xxx

cd 你的插件目录
ncc wow addons list                  # 查询插件 ID
ncc wow addons init --id 123         # 生成 ncc.json 关联插件

ncc wow addons push --dry-run        # 预检：校验参数并试打包，不上传
ncc wow addons push --version 2.0.4 --changelog "修复了..."   # 正式发布
```

## 与 AI 协作

CLI 全程非交互、支持 `-o json` 结构化输出，适合交给 AI 助手代劳。把下面对应场景的提示词复制给它（尖括号内容按需替换），由它调用 ncc 完成整个流程。开始前请先完成上文的安装与登录（或把「AI 助手一键安装」的提示词一并发给它）。

### 场景一：从零创建新插件并发布首个版本

本地已写好插件（目录里有 .toc 文件），线上还没有这个插件：

```
我本机的 <插件目录路径> 是一个魔兽世界插件目录，帮我用 ncc 把它发布到新手盒子创作者中心：
1. 先运行 ncc docs 阅读完整文档，后续遇到报错按文档处理
2. 运行 ncc wow addons categories 查分类表，结合我的插件内容选好分类，创建前跟我确认插件名称、简介和分类
3. 用 ncc wow addons create 创建插件（图标和截图用 <图片路径> 这些本地图片）
4. 在插件目录运行 ncc wow addons init --id <上一步返回的插件ID> 完成关联
5. 先 ncc wow addons push --dry-run 预检，通过后正式 push 发布首个版本（版本号 1.0.0，更新日志写「首个版本」）
```

### 场景二：连接线上已上传的插件

插件之前在网页端上传过，本地有工程目录，想改用 CLI 发版：

```
我本机的 <插件目录路径> 对应我在新手盒子已上传的插件「<插件名>」，帮我把它们关联起来：
1. 先运行 ncc docs 阅读完整文档
2. 运行 ncc wow addons list --keyword <插件名> 找到插件 ID，跟我确认是哪一个
3. 在插件目录运行 ncc wow addons init --id <插件ID> 完成关联
4. 之后每次发版：先 ncc wow addons push --dry-run 预检，再 push --version <新版本号> --changelog <更新说明> 发布
```

### 场景三：把线上插件初始化到本地（换机器 / 从零接手）

本地没有工程，想把线上最新版本拉下来作为标准工程继续维护——对空目录 `init` 会自动完成下载、解压与配置：

```
帮我把新手盒子上我的插件「<插件名>」初始化到本机 <目标目录，空目录或不存在的目录都行>：
1. 先运行 ncc docs 阅读完整文档
2. 运行 ncc wow addons list --keyword <插件名> 找到插件 ID，跟我确认是哪一个
3. 对目标目录运行 ncc wow addons init --id <插件ID>：目录为空时会自动下载线上最新版本落地为标准工程并配置好 ncc.json
4. 完成后运行 ncc wow addons info <插件ID>，把线上当前版本报给我，确认本地工程与线上一致
```

本地工程已经关联过、只是想追平线上最新版本（线上被网页端或其他机器更新过）时，不用重新克隆——在工程目录让 AI 运行 `ncc wow addons sync --yes` 即可（覆盖本地内容文件，ncc.json 与 ignore 规则命中的本地文件保留）。

这些提示词只是起点：让 AI 助手先运行 `ncc docs`，它就能按文档自行组合命令完成更复杂的诉求（批量查看和回复评论、更新配置分享正文、给帖子传附件等）。

## 命令参考

| 命令 | 说明 |
|------|------|
| `ncc login --token ncc_xxx` | 登录（--token 全程免交互） |
| `ncc logout` | 登出，清除本地令牌 |
| `ncc whoami` | 当前创作者身份 / 令牌信息 / 模块权限 |
| `ncc config` | 查看本地配置（令牌脱敏） |
| `ncc docs` | 输出完整使用教程与规范 |
| `ncc completion <shell>` | 输出 tab 补全脚本（bash / zsh / powershell），追加到 shell 配置文件后重开终端生效 |
| `ncc wow addons list [page]` | 我的插件列表（查询 mod_id，支持 --keyword 搜索；`ncc wow addons list 2` 直接翻页） |
| `ncc wow addons info <mod_id>` | 插件详情：审核/发布状态、当前信息（简介/分类/图片/官网）、最新版本与下载链接 |
| `ncc wow addons create --name --description <text\|@file> --categories <ids> --logo <file\|url> --screenshots <items>` | 创建新插件（图标/截图可传本地图片自动上传或已上传链接）；返回插件 ID，随后 init 关联目录、push 上传插件文件。删除只能在网页端操作 |
| `ncc wow addons edit <mod_id> [--name] [--description <text\|@file>] [--intro] [--categories] [--logo] [--screenshots] [--private\|--public] [--subscribe-level N]` | 编辑已发布插件的信息：只改传入项，其余字段保持不变，不会误清空；改动公开内容会重新进入审核 |
| `ncc wow addons categories` | 插件分类表（创建时用 ID 选择分类） |
| `ncc wow addons init [dir] --id <mod_id>` | 在插件目录生成 ncc.json（自动回填最近一次的适配版本）；一个目录只能 init 一次，且必须是插件目录或整合包父目录（.toc 结构检查）；对**空目录**执行则自动下载该插件线上最新版本落地为完整工程（插件代码 + ncc.json + 描述正文 description.md） |
| `ncc wow addons push [dir]` | 打包目录并上传新版本（核心命令，建议先 --dry-run） |
| `ncc wow addons pack [dir] [--version <v>] [--out <path>]` | 纯离线打包为本地 zip，不上传、无需登录（文件名 `<目录名>-<版本号>.zip`，版本号缺省读 ncc.json） |
| `ncc wow addons sync [dir] --yes` | 用线上最新版本整体覆盖本地工程内容（插件 ID 读 ncc.json）——线上被网页端/其他机器更新后本地追平用。可替换区与打包收录范围一致：会进包的内容文件以线上为准替换，打包忽略的（ncc.json/隐藏文件/ignore 命中的素材源）一律保留；覆盖不可恢复须附 --yes 确认，同步后 game_versions 自动回填 |
| `ncc wow addons versions --id <mod_id> [page]` | 版本文件列表（查询 file_id，按上传时间倒序，命令尾部加页码翻页） |
| `ncc wow addons changelog <file_id> [--set <text>]` | 查看 / 编辑版本更新日志 |
| `ncc wow addons comments list <mod_id> [page]` | 某个插件收到的评价列表（含评分/点赞/热门回复；--unreplied 只看未回复的） |
| `ncc wow addons comments reply <review_id> --content <text\|@file>` | 回复一条插件评价（回复先进平台审核后公开） |
| `ncc wow wa list [page]` | 我的字符串列表（查询 wa_id，支持 --keyword 搜索、--paid/--free 过滤） |
| `ncc wow wa info <wa_id>` | 字符串详情：审核/公开状态、当前信息（简介/分类/图片）、字符串模式与版本 |
| `ncc wow wa publish --name --description <text\|@file> --wa-str <text\|@file> --game-version <id\|名称> --categories <ids> --thumbnail <file\|url>` | 发布字符串（单字符串形态，多字符串与附件走网页端）；付费内容进入人工审核。删除只能在网页端操作 |
| `ncc wow wa edit <wa_id> [--name] [--description <text\|@file>] [--intro] [--categories] [--thumbnail] [--images] [--private\|--public] [--price <元>] [--subscribe-level N]` | 编辑已发布字符串的信息：只改传入项，其余字段（含价格/付费有效期/可见性）保持不变，不指定不会归零或清空；改动付费/公开内容会重新进入审核。多字符串请用网页端，字符串内容更新走 push |
| `ncc wow wa categories --game-version <id\|名称>` | 字符串分类表（按游戏版本查询，发布时用 ID 选择分类） |
| `ncc wow wa init [dir] --id <wa_id>` | 把线上字符串完整落地为本地工程（只支持空目录）：字符串内容 + 描述正文 description.md + project.json（名称/简介/版本/适配版本/价格/可见性快照） |
| `ncc wow wa pull <wa_id> [--out <path>]` | 拉取字符串内容保存到本地文件（默认 `wa_<ID>_v<版本>.txt`），用于本地编辑与备份 |
| `ncc wow wa push <wa_id> --file <path> --log <text\|@file> [--version <v>]` | 推送本地文件为字符串新版本；更新日志必填，版本号缺省自动递增修订号。多字符串模式仅支持 pull，更新请走创作者中心网页端 |
| `ncc wow wa comments list <wa_id> [page]` | 某条字符串收到的评价列表（--unreplied 只看未回复的） |
| `ncc wow wa comments reply <review_id> --content <text\|@file>` | 回复一条字符串评价 |
| `ncc wow uipack list [page]` | 我的配置分享列表（查询配置 ID，支持 --keyword 搜索、--paid/--free 过滤） |
| `ncc wow uipack info <config_id>` | 配置分享详情：审核/公开状态、来源云端备份与分享角色、摘要与正文格式（正文全文用 pull 拉取） |
| `ncc wow uipack publish --backup <backup_id> --title --content <text\|@file> --images <items> [--role <id>]` | 基于云端备份发布配置分享（插件关联与忽略清单从备份构成自动推导=网页端全选）；备份包含 WTF 角色配置时必须用 `--role` 选定一个分享角色（角色数据 ID 用 `cloudbackup info` 查询，漏传时错误信息会列出可选角色）；公开发布需认证作者。删除只能在网页端操作 |
| `ncc wow uipack init [dir] --id <config_id>` | 把线上配置分享完整落地为本地工程（只支持空目录）：正文 + project.json（标题/摘要 + 所基于的云端备份信息 + 选中的 WTF 分享角色快照） |
| `ncc wow uipack pull <config_id> [--out <path>]` | 拉取正文内容保存到本地文件（默认 `uipack_<ID>.md`），用于本地编辑与备份 |
| `ncc wow uipack push <config_id> [--file <path>] [--title <text>] [--intro <text\|@file>]` | 更新文本内容（正文/标题/摘要至少一项）；正文仅支持 Markdown 格式，HTML 富文本存量请走网页端。版本更新请通过盒子客户端完成 |
| `ncc wow uipack comments list <config_id> [page]` | 某个配置分享收到的评价列表（--unreplied 只看未回复的） |
| `ncc wow uipack comments reply <review_id> --content <text\|@file>` | 回复一条配置分享评价 |
| `ncc wow media upload <file> --for uipack\|addons\|wa` | 上传本地图片取得平台链接（图片 png/jpg/jpeg/gif/webp/bmp/ico、视频 mp4；上传即进平台内容审查）；用于正文嵌图与创建内容的图标/截图/展示图。社区帖子用 `ncc community media upload` |
| `ncc wow cloudbackup list` | 云端备份历史记录（按备份时间倒序），含内容构成计数、被引用的配置分享数与账户槽位使用 |
| `ncc wow cloudbackup info <backup_id>` | 单个备份基础信息：插件构成清单（已知插件/未知插件/字体/材质）、游戏账号与角色配置结构（角色附带角色数据 ID，发布配置分享 `--role` 用它）、被引用的配置分享；备份的上传与恢复请通过盒子客户端完成 |
| `ncc wow ref <addons\|wa\|uipack> <id> [--link] [--game-version <id\|名称>]` | 生成正文内联引用代码（默认卡片形态，`--link` 换链接形态），原样粘进正文即可，发布后渲染为对应卡片/链接；只能引用自己名下的内容，`--game-version` 仅 addons 有效。`uipack pull` 与 `post info` 会解析并列出正文中已有的引用清单 |
| `ncc community post list [page]` | 我的社区帖子列表（查询帖子 ID 与状态，支持 --keyword 搜索、--private/--public 过滤） |
| `ncc community post info <post_id>` | 帖子详情：正文/话题/状态与计数，以及附件清单（附件序号供 download/detach 引用） |
| `ncc community post init [dir] --id <post_id>` | 把线上帖子完整落地为本地工程（只支持空目录）：正文文件 + 全部附件下载到 `attachments/` + project.json（标题/摘要/话题/类型/可见性与附件清单快照）；正文编辑后 `post edit` 回写，附件调整用 attach/detach |
| `ncc community post pull <post_id> [--out <path>]` | 拉取帖子正文保存到本地文件（默认 `post_<ID>.md`），用于本地编辑与备份；编辑后 `post edit --content @文件` 回写（仅 Markdown 帖可回写，HTML 存量仅备份） |
| `ncc community post publish --content <text\|@file>` | 发布纯文本帖子（Markdown，需已开通频道；--title/--intro/--topics/--type/--private 可选）；发布后可用 attach 挂附件 |
| `ncc community post edit <post_id>` | 编辑帖子文本与可见性（--title/--content/--intro/--public/--private 至少一项）；正文仅 Markdown 帖可编辑 |
| `ncc community post delete <post_id> --yes` | 删除帖子（不可恢复，必须附 --yes 确认） |
| `ncc community post attach <post_id> <file...>` | 上传本地文件并追加为帖子附件（图片/mp4/zip/rar/7z/tar/gz，每帖最多 10 个）；文件走网盘直传，大文件分块并发+秒传 |
| `ncc community post detach <post_id> --index <n> --yes` | 移除帖子附件（序号从 info 查看；只解除挂载关系，必须附 --yes 确认） |
| `ncc community post download <post_id> [--index <n>\|--all]` | 下载帖子附件到本地（--out 指定保存目录；只有一个附件时可省略 --index） |
| `ncc community post comments [page]` | 我的帖子收到的评论（跨帖聚合，--post 按帖筛选、--unreplied/--replied 过滤），含未回复计数与我的回复标记 |
| `ncc community post comment-reply <comment_id> --content <text\|@file>` | 回复一条帖子评论（自动@被回复用户） |
| `ncc community post comment-delete <comment_id> --yes` | 删除帖子评论（自己帖子下的任意评论；一级评论连带其回复，必须附 --yes 确认） |
| `ncc community media upload <file>` | 上传本地图片取得平台链接，用于帖子正文 Markdown 嵌图 |

全局参数：`-o text|json`（默认 text）/ `-c` 紧凑 JSON / `--token`

## push 的参数取值规则

### 版本名 --version

取值优先级：`--version` > ncc.json 的 `version` 字段 > 报错。
版本名是自由文本，同一插件内不可重复；报错时会附带当前最新版本名与建议版本号。

### 适配客户端版本 --game-versions

支持两种写法，未指定时读 ncc.json 的 `game_versions`：

```
# 1. 显式版本串（必须在平台支持列表内）
--game-versions 11.2.7,12.1.0

# 2. 自动检测（读取目录内 .toc 的 "## Interface:"）
--game-versions auto
```

只关联插件实际适配的当前客户端版本即可，不支持按游戏版本整组选择——整组包含大量历史客户端版本，会让版本关联失真。

### 更新日志 --changelog

直接给文本，或 `@CHANGELOG.md` 从文件读取；未指定时若 ncc.json 配置了 `changelog_file` 且文件存在则自动读取。

## ncc.json 配置说明

```jsonc
{
  "game": "wow",
  "type": "mod",
  "id": 123,                       // 插件 ID
  "name": "MyAddon",               // 插件名（仅展示用）
  "version": "2.0.4",              // 下次 push 的版本名（也可用 --version 传入）
  "game_versions": ["12.1.0"],     // 适配版本（显式版本串，init 自动回填）
  "changelog_file": "CHANGELOG.md", // push 时自动读取的日志文件（可选）
  "ignore": ["*.psd", "node_modules/**"],  // 打包排除规则（可选）
  "bundle": ["MyAddon_Options"]    // 附属模块目录名清单（可选，多模块形态用，见下）
}
```

打包自动识别目录形态：单体插件（目录自己带 .toc）内容包在目录名文件夹下，与手动压缩插件文件夹一致；
整合包（目录下多个插件文件夹、各自带 .toc）子文件夹直接作为压缩包顶层，与整合包发布形态一致——无需任何额外配置，init/push 用法与单体完全相同。
整合包顶层散文件（与 ncc.json 同层的 README、CHANGELOG.md 等）不进包，压缩包顶层只有插件文件夹。
默认排除 .git / .ncc / ncc.json / 隐藏文件 / *.zip / addon_version.txt（平台安装插件时写入的版本标记文件）；压缩包上限 2048MB。
排除规则也可写在打包根目录的 `.nccignore` 文件里（一行一条，支持 # 注释；无 `.nccignore` 时自动读 `.gitignore`，与 npm 发包约定一致），与 ncc.json 的 `ignore` 数组取并集；不含 `/` 的规则在任意层级匹配。
`pack` 与 `push` 打包行为一致，`pack` 仅落地本地 zip 不上传，适合离线自查或手动分发。
`init` 只支持一次：已有 ncc.json 的目录再次 `init` 会报错 `already_initialized`——更换关联插件直接编辑 ncc.json 的 `id` 字段，确要重新生成先删除 ncc.json。init 时会检查目录结构：必须是插件目录（自带 .toc）或整合包父目录（子目录各自带 .toc），否则报错 `toc_not_found`，不会关联到错误目录。
对**空目录**（或不存在的目录）执行 `init --id <插件ID>` 进入克隆模式：自动下载该插件线上最新版本解压落地为标准工程并生成 ncc.json——换机器或从零接手线上插件时一条命令完成本地工程初始化，落地后直接可改可 push（该插件线上还没有任何版本文件时会报错提示）。

### 多模块打包 bundle（工程在游戏目录、主插件+附属模块形态）

一个产品由主插件和多个附属模块组成、且各模块直接散在游戏 AddOns 目录同层时（如 MyAddon + MyAddon_Options），在主插件目录的 ncc.json 里声明 `bundle` 附属模块目录名清单。完整规则集：

1. **成员**：主插件目录（ncc.json 所在目录）无条件进包，不写进 bundle（写了视为冗余忽略）；bundle 项只接受主插件同层的目录名，不接受路径；重复项去重。
2. **校验**：主插件目录与每个附属模块目录都必须自带 .toc，附属模块目录必须存在，否则报错 manifest_invalid。独立工程整合包（模块在工程子目录下）不要用 bundle，走自动检测。
3. **布局**：每个模块在 zip 内以自己的目录名作顶层文件夹，与整合包发布形态一致。
4. **适配版本**：`--game-versions auto` 聚合主插件与全部附属模块 .toc 的 Interface 声明（并集去重）。
5. **排除规则两层，全部是黑名单、取并集、无优先级冲突**：产品级 = 主插件 ncc.json 的 `ignore` 数组作用于全部模块；模块级 = 每个模块目录（含主插件自己）各自的 `.nccignore`（无则回落该目录的 `.gitignore`）只作用于该模块自身。两层匹配基准都是模块内相对路径（不含模块名前缀）；内置默认排除在每个模块内同样生效。
6. **兼容**：`bundle` 缺省或为空数组时行为与旧版本完全一致（单体/整合包自动检测）。

## 自动化与 CI 集成

- 默认 text 输出是给人看的精简视图（状态转文本并着色、时间转本地时区、列表带分页指引）；脚本调用请加 `-o json`：stdout 输出规范化字段的稳定 JSON（字段名语义化，枚举同时含数值与 `*_text` 中文文本；成功是数据，失败是 `{error, message, hint}`），进度提示走 stderr。
- 退出码：0 成功 / 1 业务错误 / 2 鉴权失败（需重新登录）/ 3 网络错误（可重试）。
- CI 环境用环境变量 `NCC_TOKEN` 传令牌（免落盘）。
- 触发限额（quota_exceeded）时请勿循环重试，改用创作者中心网页操作。

GitHub Actions 示例（把令牌存入仓库 Secret `NCC_TOKEN`）：

```yaml
name: release
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm i -g @newbeebox/newbeebox-creator-center-cli@latest
      - run: ncc wow addons push --version "${GITHUB_REF_NAME#v}" -o json
        env:
          NCC_TOKEN: ${{ secrets.NCC_TOKEN }}
```

## 错误码参考（-o json 时 stdout 的 error 字段）

| 错误码 | 含义与处理 |
|--------|-----------|
| `auth_failed` | 令牌无效或未登录 → 重新创建令牌并 ncc login |
| `network_error` | 网络故障 → 可重试 |
| `missing_version` | 缺版本名 → 参考返回的 suggested_version |
| `version_exists` | 版本名重复 → 换一个版本名 |
| `missing_game_versions` | 缺适配版本 → 参考返回的分组清单 |
| `invalid_game_version` | 版本写法不识别 → 从返回的版本清单中选择显式版本串 |
| `toc_not_found` | 目录里没找到 .toc（init 结构检查 / auto 检测失败）→ 确认目录 / 改用显式版本串 |
| `already_initialized` | 目录已有 ncc.json → 更换关联直接编辑 id 字段，重新生成先删 ncc.json |
| `need_confirm` | 删除/覆盖类操作（post delete/detach、addons sync 等）需要确认 → 按 hint 附 --yes 重试 |
| `file_too_large` | 压缩包超 2048MB → 用 ignore 规则排除大文件 |
| `write_failed` | 本地写 zip 失败 → 确认输出目录存在且有写权限 |
| `quota_exceeded` | 触发平台限额 → 次日再试或走网页端 |
| `cli_version_outdated` | CLI 版本过低被拦截 → npm i -g @newbeebox/newbeebox-creator-center-cli@latest 升级 |
| `cli_disabled` | 平台临时关闭 CLI 服务 → 走网页端 |
| `cli_not_authorized` | CLI 功能内测中，当前账号未开通 → 走网页端 |
| `mod_not_found` | 插件不存在或不属于当前账号 |
| `nbbcore_missing` | 附件传输组件未安装或加载失败（仅 Windows/macOS 可用）→ 按 hint 中的命令补装 |
| `upload_failed` / `download_failed` | 附件网盘传输失败 → 可重试，多次失败检查网络 |
| `invalid_usage` | 命令用法错误（缺参数/未知选项等）→ 在命令后加 --help 查看用法 |

## 常见问题

- **看不到创作者中心的「CLI 令牌」入口？** CLI 功能内测中，仅部分创作者开放，后续将逐步全量。
- **上传后看不到新版本？** 付费插件需人工审核通过后对外可见。
- **令牌忘了？** 令牌明文仅创建时展示一次，丢失请吊销后重新创建。
- **提示版本过低？** 运行 `npm i -g @newbeebox/newbeebox-creator-center-cli@latest` 升级到最新版。
- **令牌泄露了？** 立即前往令牌管理页吊销，吊销即时生效。
