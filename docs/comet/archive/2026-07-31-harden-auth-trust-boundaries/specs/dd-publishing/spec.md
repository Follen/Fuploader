# 网易 DD 插件、配置与 WA 完整发布规格

## 官方客户端 adapter

DD provider 仅支持 Windows 官方 DD 客户端。安装发现顺序为：显式环境覆盖、正在运行的
`netease_dd.exe` 路径、卸载/安装注册信息、DD 用户配置、已知安装根目录的版本子目录。
候选必须含 `netease_dd.exe`、`ccvoicehub.res`、`ccsub64` 和所需原生模块；多个版本选择
通过验证的最高版本，并把版本写入脱敏 doctor 输出。全部失败才要求用户提供路径。

adapter 使用该版本 `netease_dd.exe` 启动离屏 Python sidecar，调用官方
`AccountCredStorage`、`MobileReLoginFlow`、`JwtHelper`、`UiApiClient`、`NepWrapper`。
不解析凭据库或复刻签名。作者请求先完成 `/login/dflogin`、`/server/ts` 和 NEP 签名。

稳定独立 `clientNo` 保存在 `%APPDATA%/CCVoiceHub/Fupload/sidecar-device.json`，格式为
版本化 32 位十六进制值。首次缺失时原子创建，后续复用；格式错误时拒绝启动，不静默替换。
文件不进入 Git/Skill，不输出值。每个 Windows 用户只允许一个 sidecar，GUI DD 可并存。

## 公共字段与动态依赖

三类资源的公共商业/发布字段为：`game_type`、`scope`、`share_code_life_type`、`need_buy`、
`price_fen`、`buy_life_type`、`jump_room`、`room_id`、`channel_id`、`channel_type`、
`sync_room`、`creation_statement`、`with_associate`、`associated_acts`、
`need_anchor_vip`、`vip_levels`。平台动态读取游戏类型/版本、频道、作者内容和会员；
分享/购买有效期使用官方前端枚举，不能误用返回赛季记录的 `/act/life_type_cfgs`。

条件归一化必须忠实前端：私密清空会员并关闭同步；未关联房间清空 room/channel 并关闭
同步；未关联内容清空 associated_acts；免费时价格归零但保留前端默认且动态校验的
`buy_life_type=seven_day`；付费/会员开启时校验价格、有效期或会员等级。
`associated_acts` 只发送 `{sn,act_type}`。所有金额输入明确单位并在 wire 层转换为分。

## 插件字段与动作

插件完整字段为：公共字段加 `game_versions`、`addon_type`、`name`、`description`、`logo`、
`detail_imgs`、`primary_category_id`、`second_category_ids`、`detail_url`、`release_type`、
`version`、`html_desc`、`update_desc`；modify 另含 `sn`。

create 可设置全部创建字段并按需上传 logo、详情图和插件包。update 只允许插件文件、
`version/game_versions/release_type/update_desc` 及更新同步相关字段；edit 允许资料、分类、
媒体和公共商业/关联/公开字段。若生产 UI 将某字段锁定为 create-only，update/edit 输入该
字段本地拒绝并保留 GET 值。底层 create 用 `/addon/create`，update/edit 都先读取
`detail_v2`（必要时 detail），映射 `latest_version`，最后用资源专用完整 payload 调
`/addon/modify`。

插件上传使用 `/file/upload -> PUT -> d_url`，资源参数为 `file_type=a19-ui-res`、
`business_id=addon`；图片使用 `a19-ui-media/img`。版本历史用于重复保护和读回。

## 配置字段与动作

配置完整顶层字段为：`backup_sn`、`scope`、`title`、`brief_desc`、`desc`、`update_desc`、
`display_imgs`、七组内容容器、可选 `retail_ui_config`，以及全部公共商业字段；modify 另含
`share_sn`。七组内容为 `known_addon`、`unknown_addon`、`wtf`、`material`、`font`、
`known_wa`、`unknown_wa`。

create/update 必须先读取 `/backup/list` 与 `/backup/detail`。items 从备份完整对象重建，
不能只提交名称/ID；WTF 按 account/server/role 三级分组；unknown WA 按所选账号映射补 id。
`inner_version` 新项为 1；update 保留旧 map，并仅对“本次增量更新”显式选中的现有项加 1。

正式服 `retail_ui_config` 覆盖 `edit_mode`、`cool_down`、`enable_dd_setup_wizard`：编辑模式
全账号最多 5 个且有一个默认项；冷却管理器每个 spec_tag 最多一个；对象保留备份返回的
全部字段。切换 backup_sn 清空并重新选择全部内容；切换 WTF 账号清空依赖账号的 WA 选择。

`backup-get` 不输出 `import_string` 或原始正式服配置，而为编辑模式和冷却配置返回绑定该备份
的 opaque selector 与安全显示元数据。写输入只接受 selector、默认编辑模式 selector 和向导
开关；provider 在写入前从同一份原始备份解析并恢复完整对象。跨备份 selector、原始对象透传、
重复项、超过五个编辑模式、默认项不在选择中或同一 spec_tag 多个冷却配置均本地拒绝。

create 创建完整分享；update 只切换/更新 backup 和七组内容、inner_version、WTF、正式服
配置及更新公告；edit 只修改标题、描述、图片、公共商业/关联/公开字段。update/edit 都先
读取 `/share/detail` 与对应备份详情，最后调用资源专用完整 `/share/modify` payload。

## WA/字符串字段与动作

WA 完整字段为：公共字段加 `name`、`game_version`、`brief_desc`、`display_imgs`、
`category_ids`、`content`、`desc`、`update_desc`、`version`、`with_file`、`file_path`、
`file_install_path`、`parse_wa_uid`、`parse_wa_id`；modify 另含 `sn`。

分类从 `/wa/categories` 动态读取，最多 5 项；游戏版本单选。版本只允许数字，update 必须
严格增加。`content` 以 `!WA:2!` 开头且变化时必须调用 DD 原生解析 bridge 重新取得
`parse_wa_uid/parse_wa_id`；非 WA2 内容清空二者。`with_file=true` 时材质 ZIP 和安装路径
必填，上传使用 `a19-ui-res/wa` 且最大 50 MiB。

create 设置完整首次内容；update 只允许 content/version/update_desc、材质和同步相关字段；
edit 允许名称、版本归属、分类、说明、媒体和公共商业/关联/公开字段。update/edit 都先读取
`/wa/detail` 及动态选项，再用完整 `/wa/modify` payload 提交。

## Builder、安全与验证

插件、配置、WA 必须有三套独立 form model 和 wire builder，且 create/update/edit 使用
动作白名单。GET 详情中的审核、统计、作者和临时字段不提交；完整 payload、token、JWT、
Cookie、signed URL 和原始字符串不记录。写成功要求业务 `code=0`，但“接受提交”不等于
审核通过；每次写后使用详情、列表或版本接口读回。

最终验收必须使用当前已登录 DD 客户端和明确标识的隔离测试对象，对插件、配置、WA 各执行
真实 create、update、edit。每个动作成功后立即读回目标详情或版本并核对关键字段；失败时
停止后续动作并记录已创建对象和安全重试入口。测试不修改既有正式对象、不调用 delete，
所有保留测试对象的 `sn/share_sn`、名称、动作结果和审核状态写入验证报告。

最终验证必须从 `options game-types` 动态枚举当时全部游戏 build，并对每个 build 查询插件
版本、WA 分类、作者列表和云备份分布。build-specific 版本、分类、备份和资源 ID 必须保持
隔离，任何跨 build 复用均在本地或平台写入前失败。插件、WA 和配置的逐 build 真实写入范围
覆盖动态返回的全部 DD build；每个动作立即读回并在报告记录保留对象。

除主资源九条写动作外，session doctor、全部 options、分类、版本、列表、详情、备份详情、
上传和 DD 原生解析等 CLI 暴露接口都必须有生产环境验证结论。验证后继续审计 builder allowlist、
敏感输出、并发单例、版本漂移、最终一致性和错误恢复，修复后重跑相关真实与回归测试。

公开 DD provider/CLI 不提供 delete。全量验证结束后，分发范围之外的 `analyze/` 清理流程
可以调用 `/addon/delete`、`/share/delete`、`/wa/delete`，但只接受验证报告中本次创建且已
读回确认的 SN；删除后再次 list/get 确认，不确定结果不得盲目重发或扩大清理范围。

候选 executable 在任何启动前必须通过 Windows Authenticode 链验证，且 signer 组织属于源码
维护的官方 NetEase 发布者允许集合。仅具备相同文件名、资源包和目录结构不构成有效候选；无
签名、无效签名、未知发布者或无法完成验证时排除。允许集合基于稳定组织身份，不锁定当前单个
证书 thumbprint，以支持官方证书轮换。

sidecar 状态目录使用 Windows Known Folder 派生的 `CCVoiceHub/Fupload`，不接受 `APPDATA`
重定向。doctor 返回所选安装来源、版本、签名状态、发布者和状态目录来源，但不输出 clientNo
或其他凭据。`FUPLOAD_DD_DIR`/`NETEASE_DD_DIR` 不再作为未经验证的优先候选；自动发现全部失败
时只报告安装错误，不执行伪造目录中的 binary。
