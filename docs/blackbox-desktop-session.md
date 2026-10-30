# 小黑盒客户端会话复用调查

调查日期：2026-10-30。客户端版本：2.10.19。

## 本机只读实测

不启动浏览器或无头浏览器，不操作界面，不重新登录，不执行发布或删除。
使用本机仍有效的旧客户端缓存 Cookie，加新版客户端参数和请求签名，直接访问官方 HTTPS 服务：

| 接口 | 结果 |
| --- | --- |
| POST `/wow/v2/get_user_info/` | HTTP 200，`status=ok` |
| POST `/wow/get_user_configuration_backup_list/` | HTTP 200，`status=ok`，备份列表为空 |
| POST `/wow/v2/share/list/`，`my_publish=1` | HTTP 200，`status=ok`，自有分享列表为空 |
| GET `/wow/open_platform/module/list/` | HTTP 200，`status=relogin` |
| POST `/account/gen_token_for_web_login/`，空表单 | HTTP 200，`status=ok`，没有返回有效 token |
| 同一交换接口，表单含客户端使用的 `_t` 毫秒时间戳 | HTTP 200，`status=ok`，没有返回有效 token |

前四个接口使用 `workshopapi.xiaoheihe.cn`；交换接口使用 `api.xiaoheihe.cn`。
结论是配置分享、云备份与 Open 插件作者后台的认证能力不同。普通账号可查询前两类，不代表已经取得 Open 作者会话。
本轮未验证通过该会话创建、上传、修改或删除备份及配置分享。

## 新版协议与存储

静态来源为签名有效的官方安装程序资源 `resources/app.asar` 及捆绑的 `heybox.wow-workshop` 扩展 1.1.3。

- 请求由 `host.backend.request.raw` 交给主进程的官方服务适配器，明确保留 Workshop 服务目标。
- 客户端标记为 `x_app=heybox_pc_v2`、`x_client_type=pc`、Windows、64 位。
- Workshop 服务采用兼容版本 `999.0.4`；普通 API 采用客户端版本 `2.10.19`，并带版本、渠道、语言和设备字段。
- 原生签名对交错后的输入截取前 20 字符，再做 MD5 派生；时间输入为请求时间加一秒。不要直接混用网页签名实现。
- 当前登录权威来源为 Electron 的 `persist:heybox` 会话，位于 `%APPDATA%/HeyboxDesktop/desktop/Partitions/heybox`。
- `%APPDATA%/heybox-pc-launcher/config.json` 仅用于旧版迁移。它本机仍保存有效账号会话，但不能作为新版当前账号的权威来源。

当前账号快照由主进程内存中的 `auth.snapshot.query` / `host.account.currentUser.get` 提供，没有发现发行版对外开放的 HTTP 认证代理。
扩展的 parentPort IPC 验证宿主实例和部署身份，不能将其视为公开本机 RPC。Agent 游戏管道也不提供认证或后端请求能力。

## 尚未接入默认认证的原因

本机当前分区 Cookie 数据库被独占打开（Win32 错误 32），普通权限也无法复制持有该文件的主进程句柄。
旧缓存账号与唯一用户 profile、今天的软件上报标记一致，但这些记录会在切换账号后保留，不能证明当前正在使用的账号。
因此没有将旧 Cookie 缓存接成默认发布来源，避免客户端切换账号后仍使用旧账号。

备份、配置分享的纯 HTTP 读取已经获得实测证据；稳定的新版当前账号绑定，以及 Open 插件作者会话交换仍未解决。
调查脚本位于本地忽略目录 `analyze/blackbox-desktop-v2/probe.py`，只输出接口状态、数量和 token 是否存在，不保存凭据。

## 后续：官网短信登录已打通

同日按用户授权测试官网手机号验证码登录。纯 HTTP 调用官方发送短信和验证码登录接口，按官网 RSA 格式加密手机号，并在成功后同步官网使用的四个会话 Cookie。
官网要求的设备风险参数使用本机官方客户端已有设备 token；没有启动浏览器、无头浏览器或操作界面。

登录后 Open 插件作者列表和云备份列表均返回 `status=ok`。会话使用 Windows CurrentUser DPAPI 加密保存在 `%LOCALAPPDATA%/Fuploader/blackbox-http-session.dpapi`。
结束登录进程后，另起 Python 进程加载加密会话，两项只读查询再次成功。手机号、验证码和解密 Cookie 均未写入研究记录或仓库。

本地研究脚本：`analyze/blackbox-phone-login/phone_login.py`；`--verify-saved` 只读验证已保存会话，不发短信。该链路现已接入 Fupload 默认 HTTP 登录入口，正式命令与字段见[平台字段总表](../fupload/references/platform-fields.md#blackbox)。

## 恢复和续期实测

`GET https://api.xiaoheihe.cn/account/restore_login` 已用上述加密会话验证成功，未发送新验证码。
接口返回相同 pkey、当前账号及 `expire_at`，同时通过 `Set-Cookie` 更新会话期限。
保存时原期限为 2026-11-06 20:44:48；本次续期返回 2026-11-06 20:50:18（北京时间）。
更新后另起进程加载加密文件，Open 作者列表和云备份查询仍成功。

同时移除 `x_xhh_tokenid` 做对照，恢复登录、作者列表和云备份读取均为 `status=ok`。
因此实验脚本给设备 token 暂设的一小时本地保存期限，不是登录会话的一小时服务端寿命。
官网风控 Cookie 实际设置为 14 天；源码通过 SDK 重新取得设备凭据，不存在仅凭旧 B token 延期的已知接口。
目前验证的是恢复和上述读取不依赖该风控 token，不能推定所有受风控操作均不需要设备验证。

实验脚本新增 `--renew`：只恢复现有会话，核对账号、服务器期限及两项只读接口后原子替换 DPAPI 文件。
不调用发送短信或验证码登录接口；服务端拒绝、返回其他账号、期限异常或读回失败时不保存新状态。
本次四个本地回归测试覆盖密钥轮换、恢复拒绝、身份/期限异常及读回失败。
本次实测续期使服务器期限向后延长。按用户选择，正式入口只在使用时续期，不运行后台维护；服务器拒绝恢复时返回重新认证需求。
