# 黑盒工坊操作

完整字段、类型、条件和接口映射统一见[平台字段总表](platform-fields.md#blackbox)。本文件只说明登录交互与执行顺序。

## 登录：CLI 与 Agent 分步交互

先执行 `blackbox session doctor`。有有效会话时直接运行业务命令；每个 CLI 进程首次使用时恢复一次现有会话，按服务器期限更新本机加密文件。不设置后台定时任务，不自动打开浏览器，不自动发送验证码。

没有会话时，由用户选择短信或微信。写命令使用版本化 JSON，经 `--input -` 传入；手机号、验证码不放在 argv、发布记录或输出中。

| 动作 | 输入 | 返回与后续 |
| --- | --- | --- |
| `session login-start` | `method` 为 sms 时提供 `phone`；wechat 时省略手机号 | 短信发送一次后返回 `login_id`；微信返回 `login_id` 与 `image_file` |
| `session login-submit` | `login_id` 和字符串 `code` | 提交一次验证码；保留前导零；结果不明确时不重发 |
| `session login-status --login-id <id>` | 开始步骤返回的编号 | 查询短任务状态；可跨 CLI 进程恢复，不要求一个终端一直运行 |
| `session renew` | 仅动作 schema | 恢复现有登录并核对账号/期限，不发短信 |
| `session forget` | `confirm_forget=true` | 只清理 Fupload 本机登录，不请求平台账号退出 |

Schema 示例：`fupload.v1.blackbox.session.login-start`、`fupload.v1.blackbox.session.login-submit`。完整 JSON 字段见总表。

Agent 展示返回的二维码图片，让用户用微信扫码并在手机确认，再通过 login-status 查询。不要把小黑盒 App 二维码当作微信二维码。需要验证码时向用户询问，仅临时用于 login-submit。收到不明确的提交结果后，只检查状态，不重复消费同一验证码。

Cookie 和 pending 任务使用 Windows CurrentUser DPAPI 加密；待登录任务有效期五分钟。新账号只有登录和只读验证完成后才替换 active 会话。会话恢复必须与已保存账号一致；不靠旧桌面账号缓存自动认定当前用户。

短信可读取本机官方客户端已生成的设备风控字段，只有设备 token 被使用，不借用桌面账号 Cookie。缺少设备验证或遇到图形验证会返回明确状态；不自动重发短信或绕过验证。正常恢复和读取不必每小时更新风控凭据。

## 业务动作

- 插件元数据用 plugin edit；plugin update 创建新版本。已有版本修改和删除用 plugin version-edit/version-delete。整插件模块删除尚未实现。
- 配置先选备份，再读详情和内容候选。config create/update/edit 保留未修改富文本、图片和备份容器信息；更换备份必须重选内容。
- 本地备份 scan/generate 不要求登录；upload/create 使用选定的包。WTF 必须精确选择账号、服务器、角色。
- 删除先 delete-preview，再用明确 backup_ids 执行。被配置分享引用的备份拒删；引用不明时停止。
- 写入一次后读回；网络中断、验证码已提交、版本删除状态回退等情况均不自动重放写操作。

数据 API 固定为官方 HTTPS 域名和允许路由；不接受调用者提供 Cookie、token、pkey、签名、API 地址或浏览器 profile。COS 仍使用 npm 专用 Python 环境中的官方 SDK。

配置的 `Open:false` 仅表示不出现在公开列表，不提供访问隔离。实测匿名调用方仅凭分享编号就能读取正文及分享码，再凭码取得下载凭据；云备份本身的匿名直取仍被拒绝。若用户要求仅本人可访问，不能用配置分享代替云备份保存，也不能将此状态描述为私密发布。


## WA / 字符串

黑盒 WA 仅支持明确公开发布。create/update/edit 必须提供外层 `scope: "public"`；`open` 是平台原始字段，不能作为隐私开关。实测 `open:false` 和审核中状态均可能被匿名接口取回导入串，禁止把私密内容上传到此通道。

先用 `blackbox wa categories` 读取分类，再用 `wa list --strappid <分支>` 和 `wa get --strappid <分支> --slug <编号>` 选择当前作者的记录。create/update/edit/delete 使用对应版本化 schema 和 `--input PATH|-`，完整字段见[平台字段总表](platform-fields.md#blackbox)。导入串只通过输入文件或 stdin 提供，输出及错误仅保留摘要。

更新时省略的可读字段保留现有值；详情不返回的 `strappid`、`open`、`subscribeLevel` 必须显式提供。写后区分 `verified_fields` 与 `unverified_fields`，不把接口接受等同于全部字段已核对。审核状态为 1 时删除会被拒绝；确认目标状态后再操作，未知写入结果先读回，不自动重发。


## 插件版本的读回范围

版本写入返回的 `verified:true` 限定为 `verification_scope:remote_metadata`。`metadata_verified` 与 `verified_fields` 说明已核对的远端字段；`archive_verification.content_verified:false`、`public_download_verified:false` 和 `unverified_fields:["archive_bytes"]` 明确表示未确认包字节或公开下载，也不代表审核完成。

新本地ZIP创建版本时，平台会将官方上传地址转换为正式版本地址。仅当唯一新版本、名称/类型/游戏版本匹配、当前官方版本选项能唯一确定同一分支、转换前后都是严格允许的官方路径时，才接受这种元数据读回。调用者提供的任意file_url不适用。既有编辑仅在无file和无caller file_url、原URL取自本次同模块/版本的唯一记录、同ID和目标元数据匹配、前后均为同一官方分支canonical路径时，才接受server_recanonicalization；输出保留原record来源，仍不确认包字节。其它地址变化返回待核验。出现verification_required时先读回本轮确切版本，不自动重复创建或编辑。

版本列表按实际页长推进，有总数时核对完整总数，无总数时读到空页；列表不完整不能作为删除成功的证据。`version edit` 带本地ZIP会先核对原版本和官方分支，再验证同ID的新包地址确实变化；仍只声明远程元数据验证，包字节未自动验证。写入不确定时只读核对，不重复上传或提交。
