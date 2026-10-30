# 网易 DD 字段核对

## 来源与验证范围

核对 DD 100130 的官方 Python 资源包、作者网页表单及 Fupload 最终请求构建器。字段映射记录在相邻 `dd.json`，主要证据为 `dd.py` 的 `plugin_form`、`config_form`、`wa_form`、`normalize_commercial`，以及 `dd_backup.py`。`test_dd_wire_matrix.py` 对插件、配置、WA 的最终表单逐字段核对；这类本地请求测试不等于所有字段都已远程发布。

已在本机验证：普通权限借用正在运行客户端的 Cookie，作者查询和合成 ZIP 上传正常；当前六个动态游戏分支（10001、2、7、3、6、4）均完成合成备份生成、上传、改名、预览、删除及读回，测试记录已清理、原有五条备份保留。另以私密测试配置验证关联备份即使 confirm_delete=true 也拒删，并完成 2823 字符 HTML 修改与读回；随后按配置、备份顺序清理。另一邮箱账号、全部付费/频道组合、长期切号场景未做实机发布验证。

## 登录和能力边界

- `dd session doctor` 只诊断；`dd session start` 返回一个不透明任务 `session_id`，业务命令统一带 `--session`。在 `finally` 调用 `dd session stop --session <id>`；不要为每个对象创建一次会话。
- GUI 正在运行：借用其已存在的网页会话，`session_source=desktop-cookie`、`native_login_count=0`；失败就停止，不再创建另一条桌面登录，不关闭客户端。旧 `--confirm-close-gui` 参数仅兼容调用。
- GUI 未运行：读取官方自动登录凭据。邮箱是 `urs + urs_token + normal`；手机号是 `mobile + urs_mobile_token + normal|mobile_password|mobile_uplink`。只有 `mobile_password` 令 `isPassword=true`；未知组合拒绝。
- 借用会话的原始登录方式无需再次判断；停止仅清理自己的 HTTP/runtime，不请求账号退出。
- CC 频道列表依赖现有 GUI 的 CC JWT，作者 Cookie 不能直接替代。`dd_channel.py` 只在查询频道、新设或更换关联目标时使用运行时读取；现有关联目标未变则保留已核对的详情。读取权限不足时通过一次 UAC 启动同用户短时辅助，普通上传与主进程/broker仍不提权。辅助绑定 DD 100130/CPython 3.7.17 的签名、文件哈希、GUI 创建时间及当前账号 profile，通过受限命名管道只返回候选，不传递或落盘凭据。JWT 到期时使用同一现有会话的 loginToken/UID/EID/校时值按官方 GET /v1/jwt 签名申请，不新建桌面登录；取消、超时或会话变化即停止。

## 商业与可见性条件

`scope` 使用 `public|private`；它不等于免费/付费。`need_buy=true` 必须同时提供 `price_fen` 和 `buy_life_type`。`price_fen` 单位为分，只允许 0 或 10 至 20000。已有对象的外层免费/付费模式锁定；不能通过 edit 改变 `need_buy || need_anchor_vip` 的整体真假状态。

private 强制不做频道同步、不要求主播 VIP；public 插件和 WA 的 `share_code_life_type` 规范为 `forever`，public 配置不发送该字段。private 创建通常要求分享码期限，付费私密配置有单独例外。配置的 `need_buy` 最终为整数 0/1，其他资源不据此猜类型。

`jump_room=true` 要求 `room_id`；`channel_id` 与 `channel_type` 同时为空或同时有值。`sync_room=true` 要求公开、跳转房间及有效频道。关闭 `jump_room` 会清空房间、频道并关闭同步。`with_associate=false` 清空关联；true 要求非空 `associated_acts`。`need_anchor_vip=true` 要求 `vip_levels`。

`associated_acts` 每项仅 `{sn:string, act_type:"addon"|"share"|"wa"}`。VIP 等级和分类用当前动态候选 ID，不传名称/显示对象。`creation_statement` 必须是用户实际声明。

## 插件与版本

`plugin create` 需要游戏分支、当前 build 字符串、标题、简介、分类、版本类型、版本、详情正文、更新说明、Logo、至少一张详情图及 ZIP。字段表的静态可省略不代表可省掉 Logo/媒体/包：URL 与本地文件提供的是同一需求的两条入口。

`plugin update` 是新版本；`game_type` 和初次发布信息不因此开放修改。重复版本在上传前拒绝。`plugin edit` 只接受当前 Schema 列出的商业、关联、简介、Logo、详情和公告字段。公告 `update_desc` 作用于当前插件，不是任意历史版本日志。作者列表与 detail_v2 的最新版本投影可能不同；重建 modify 时优先采用作者列表的版本/包投影，读回按实际字段核对。

本地 Logo/图片先授权上传，再在最终表单放回地址；`logo_file`、`detail_img_files` 不原样发给发布接口。插件 ZIP 最终对应 `detail_url`，路径分隔符必须为 `/`。

## 配置选择与嵌套结构

依赖顺序是 `backup_sn → backup detail → WTF account/server/role → 该账号的 WA`。更换备份或账号会使原有子选择失效。

- `known_addon_ids` 按 `addon_id` 选择完整候选；`unknown_addon_ids` 实际按标量名称、对象 `name`（缺失才按 `id`）选择，不能因字段后缀就假定都是数字 ID。材质按 `name`，字体按返回的字符串或名称选择。
- WA 的 `*_wa_ids` 实际选择 `uid`；已选 WTF 账号必须有对应映射。`known_wa` 保留候选对象，`unknown_wa.id` 替换为该账号的映射 ID。不要混淆 `uid` 与内部 `id`。
- 全部 `*_update_ids` / `*_update_names` 必须为当前选择的子集。它们更新分组的 `inner_version[选择键]`，不是设置 `items[].update`；已有非零版本标记后加一，其余保留，初始为一。
- `wtf_role_ids` 使用 `backup-get` 返回的稳定角色选择器。Fupload 据此重建 `wtf.accounts[].servers[].items`，不接受原始 WTF 对象或配置文本。
- `retail_ui_config` 输入只允许 `edit_mode_selectors:string[]`、`default_edit_mode_selector:string|null`、`cool_down_selectors:string[]`、`enable_dd_setup_wizard:boolean`。选择器用于本地匹配备份；最终 wire 的 `edit_mode[account]`、`cool_down[account]` 是选中原生对象，前者补 `is_default`。最多五套编辑模式，非空时默认项必须包含在选择中；每个 `spec_tag` 最多一套冷却配置。正式服切换备份时必须重新选择，不接受原始导入字符串作为输入。
- `display_img_files` 上传后追加到现有展示图，最终总数最多 8；不是替换全部图片的隐含指令。

## WA 与附件

WA 版本必须为数字字符串。每次提交 `!WA:2!` 都调用官方解析器获得内部 `parse_wa_uid` 和 `parse_wa_id`，包括编辑时保留的原内容；这两个内部字段不是用户输入。非 WA2 不保留旧解析 ID。

`with_file=true` 的首次创建需要 ZIP 和非空 `file_install_path`；update 省略文件可保留已存在的附件。false 按官方表单保留内部路径，不把它解释成远端对象删除。WA 附件上限 50 MiB；图片及其他文件仍要通过当前授权限制。

## 云备份

`generate` 只在本机生成分组 ZIP 和 `backup-bundle.json`；`upload` 读取该包；`create` 可生成后上传或显式复用一个包。选择字段不得混同配置分享字段。

`wtf_accounts` 为 `[{account:string, include_common:boolean, roles:[{server:string,name:string}]}]`；`include_wtf_root` 单独控制 WTF 根文件。不要默认收集全部账号或角色。字体 ZIP 使用 `Fonts/`，WTF ZIP 使用 `WTF/Account/` 层级；上传前核对包 hash、目录和选择元数据。

真实协议为 `/backup/pre_create` 的五类清单、各选中组的签名对象 PUT、`/backup/finish_create`，再读 detail/list。官方仍可能返回 HTTP 对象地址；仅对已验证的官方精确域名升级 TLS，保留签名的 Content-Type 与 ACL。空组读回可为 null；不能因此误判整个备份未创建。

`name` 最多 14 字符，通过 `/backup/modify_name` 改名。删除前读取所有游戏分支的自有配置分享并解析其 `backup_sn`；有引用、缺失明细、总数/分页异常都停止。每项删除前再查一次关联，删除只发一次，并以刷新后的列表确认消失。
