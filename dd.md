# 网易 DD 客户端能力调研结论

调研日期：2026-07-30 至 2026-07-31

## 结论

从接口能力看，可以为 Fupload 增加一个与“新手盒子 provider”目标相同的 DD provider，覆盖插件、配置分享和 WA/字符串的创建与更新；但 DD 不能直接套用新手盒子的网页会话方式。当前核心方案是复用 DD 随附的原生 Python 模块和 NEP 包装器，由持有稳定独立设备身份的 sidecar 从 `cred.db` 恢复登录并完成请求签名，而不是让用户提供 token、回放网页 Cookie，或依赖 GUI WebView。

指定频道在 A 到 B 时间段内拉取消息也可实现。DD 历史接口按 `msgId` 游标分页，不支持直接传起止时间，因此必须分页取回后按 `sendTime` 在本地过滤。

2026-07-30 的运行时补充测试确认：当前 DD 主进程的频道 JWT 和作者签名会话均有效，作者侧 `/addon/addon_list`、`/addon/detail`、`/share/list` 已成功走签名 GET；但该版本没有向本机第三方程序暴露通用的聊天历史或 WebView IPC。内置 `web exec-js` 属于网易服务端下发的远程命令通道，不是 Go 程序可直接连接的本机 IPC。

本次仅调研，没有改动 Fupload 主实现。完整 builder 实测中，插件、配置分享和 WA
的 create/modify 六个端点均返回 `code=0`；插件 ZIP 重新上传 PUT 返回 HTTP 200。
创建了 3 个带 `Fupload` 标识的公开测试条目，没有删除条目或发送频道消息。早期
通用字典探针的三次插件请求曾返回 HTTP 422，属于已修正的历史反例。

无头运行时实测已补齐：原生 `MobileReLoginFlow` 可以解密并消费 DD 持久登录态，
`JwtHelper` 能换取频道 JWT；同一运行时的 `UiApiClient` 能完成作者登录和服务器
时间同步，插件/配置/WA 的 create/modify 均能生成 NEP POST 签名而不发送请求。

最关键的新结论是：sidecar 不能复用 GUI DD 的 `clientNo`，但可以持有一个独立、
稳定的 `clientNo`，以第二台设备的方式与 GUI 并存。受控测试中，GUI DD 保持登录，
sidecar 同时完成 JWT、最近 3 小时频道历史（7 条）、作者登录及六个 POST 签名；
保持并发连接 30 秒并正常退出，GUI 全程正常。

## 方案 A：稳定独立设备 sidecar

这是当前推荐实现方案：

```text
Go 主程序
  -> stdin/stdout JSONL 或当前用户 Named Pipe
  -> DD Python sidecar（稳定 clientNo + netease_dd.exe + 原生模块）
       -> AccountCredStorage
       -> MobileReLoginFlow / JwtHelper
       -> UiApiClient / NepWrapper
       -> 频道历史、作者接口
```

约束：

- sidecar 使用 [DD/sidecar-device.json](DD/sidecar-device.json) 中固定的 32 位 `clientNo`，不得每次生成。
- `clientNo` 在原生 DI 容器初始化前注入 `machine_data.clientNo`，与 GUI 的设备身份隔离。
- GUI DD 可以同时运行；GUI 和 sidecar 各自拥有独立设备会话，不共享最终 `loginToken`。
- sidecar 复用 DD 安装目录和当前 Windows 用户的 `cred.db`，不复制或改写凭据库。
- JWT、Cookie、`x-w163-token` 和 signed URL 只留在 sidecar 内存中；Go 只接收业务结果。
- `author.create/modify` 已验证真实写入，但正式实现仍应默认 dry-run，并对外部写入要求显式确认。
- sidecar 使用 `netease_dd.exe` 直接启动，不经过要求管理员权限的 `Start.exe`；更新由用户正常启动 DD 时完成。
- 当前 DD 版本固定为 `100128`，启动时校验资源版本，不匹配则拒绝运行。
- `sidecar-device.json` 不是账号凭据，但属于稳定本地设备状态；只有文件丢失或显式重建设备时才重新生成。

方案 A 已完成端到端验证，不依赖 WebView2/CDP、进程注入或管理员权限。DD GUI
可以运行，也可以关闭；关闭 GUI 只是保守回退模式，不再是方案 A 的前置条件。

`eid` 在两次复用同一 `clientNo` 的测试中分别为 `22629339`、`22629661`，说明它是
会话端点标识而非持久设备标识。判断是否重复创建设备必须看稳定 `clientNo`，不能
用 `eid` 是否变化作为依据。

## 能力与接口

作者接口基址为 `https://uiapi.w.163.com`：

| 能力 | 创建 | 更新 |
| --- | --- | --- |
| 插件 | `POST /addon/create` | `POST /addon/modify`，携带 `sn` |
| 配置分享 | `POST /share/create` | `POST /share/modify`，携带 `share_sn` |
| WA/字符串 | `POST /wa/create` | `POST /wa/modify`，携带 `sn` |

文件上传先通过 `GET /file/upload` 获取临时签名 URL，再 PUT 文件，最终把公开 `d_url` 写入业务表单；该链路已用 4,778,463 字节插件 ZIP 实测成功。端点摘要见 `DD/author-api-matrix.md`；完整字段和转换见 `DD/author-field-coverage.md`；真实 CRUD 与必须先 GET 的依赖见 `DD/author-crud-verification.md`。

## 登录态设计

DD 存在两套独立鉴权：

1. 作者 API：`/login/dflogin` 获取 UIBox token；请求携带 `x-w163-token` 和 `x-timestamp`，GET/POST 分别通过 `nepHttpGetSignedUrl`、`nepHttpPostSignedUrl` 获取 signed URL。
2. 频道 API：使用客户端登录 token 生成 MD5 seed，向 `GET https://api.cc.163.com/v1/jwt` 换短期 JWT，后续通过 `Authentication: <jwt>` 调接口。

因此后续 DD provider 应划分为两个 transport，而不是共享一个“登录 Cookie”：

```text
DD client session
  -> UIBox signed transport -> plugin/config/WA author APIs
  -> CC JWT transport       -> space/channel/message APIs
```

安全要求：凭证仅在内存中短暂使用；不复制或改写 `cred.db`；不把 token、JWT、Cookie、signed URL 或完整敏感响应写进 Fupload 配置和日志。

## 指定频道消息拉取

用户示例已经完成映射确认：

```text
展示空间号 16888
  -> teamId 144686
  -> 露露缇娅的专属空间
  -> 分类 G10150764（露露的插件包 | 提问与反馈）
  -> channelId 10075340（提问与反馈 至暗之夜，text）
```

历史接口：

```http
GET https://api.cc.163.com/v1/mixteamchat/chatMsg/list
Authentication: <jwt>
```

参数只有 `channelId`、`msgId`、`isAsc`。`msgId=0,isAsc=0` 取最新一页；使用当前最小 `msgId` 且 `isAsc=0` 向更早消息翻页；实测页大小为 30，`sendTime` 为 Unix 毫秒。

建议区间语义固定为 `A <= sendTime < B`：从最新页或已保存检查点向前分页，本地过滤，页面最早时间早于 A 后停止，按 `(channelId,msgId)` 去重，最终按 `(sendTime,msgId)` 升序输出。撤回、删除、审核态和非文本消息必须保留类型/状态语义。

## 推荐实施边界

后续实现建议分三步，每一步都可独立只读验证：

1. `dd session doctor`：校验 DD 资源版本、稳定设备状态、持久凭据可解密且 JWT 可刷新，不输出凭证。
2. `dd channel resolve/history`：先完成空间/频道解析和 A/B 消息导出；这是纯只读能力，风险最低。
3. `dd plugin/config`：沿用已验证的三套独立
   `detail -> form -> wire payload` builder、上传协议、dry-run 和写入确认；禁止用
   通用 map 透传详情。

Go 集成应把客户端原生 Python 模块封装为受控 sidecar。Go 只允许一个 sidecar
实例，并在启动前加载固定 `clientNo`；这限制的是 Fupload 自身重复启动，不限制
GUI DD 与 sidecar 并存。若状态文件损坏，应明确报错并要求确认后重建设备，不能
静默生成新值。

不要自行解析 `cred.db` 或复刻其加密格式，也不要把客户端数据文件格式当作稳定 API。方案 A 应直接调用 DD 自带的 `AccountCredStorage`、登录流程、`JwtHelper`、`UiApiClient` 和 `NepWrapper`，并对客户端版本做严格校验。

当前版本已确认“现有本机 IPC 无法调用 WebView bridge”。WebView2/CDP 方案也已
实测排除：调试端口未形成可连接端点，且带调试参数启动时 DD 界面未正常出现。
方案 A 不需要共享 GUI 的连接：它通过稳定的第二设备身份建立独立会话，因此无需
改造 DD 主进程。进程内注入/IPC 降级为备选研究，不再是当前主线。

## 已确认与未确认

已确认：

- 示例空间/频道的展示 ID 到内部 ID 映射。
- 历史消息接口、游标方向、页大小、时间字段和 JWT 请求头。
- 插件、配置分享、WA 的创建/修改端点、完整表单字段和 read-modify-write 转换。
- 作者请求必须经过 UIBox token、时间戳和客户端签名 URL。
- 固定独立 `clientNo` 的 sidecar 可与 GUI DD 同时在线。
- 最近 3 小时历史和六个作者 POST 端点签名已在并发模式下通过。
- 六个作者 create/modify 端点均已真实返回 `code=0`。
- 插件 ZIP 的 `/file/upload -> PUT -> d_url -> /addon/create` 已端到端通过。
- 配置和 WA 的 modify 已从详情接口回读；WA 版本从 `1` 更新到 `2`。

尚未确认：

- 任意展示空间号到 `teamId` 的通用解析接口。
- 作者写接口针对不同游戏类型/版本的完整服务端必填规则。
- 三个公开测试条目的最终审核结果；插件 modify 提交的新版本在审核完成前不会从
  当前公开详情和版本列表中显示。

字段覆盖结论以 `DD/author-field-coverage.md` 为准：插件和 WA 已逐项覆盖线上字段；
配置分享同时覆盖顶层字段、七组配置内容、`inner_version`、WTF 三级分组、正式服
`retail_ui_config`、增量更新选择以及所有条件清空规则。这里的“字段完整”指生产
前端静态契约已完整记录，并已在当前账号、当前 DD 版本和 `game_type=10001` 上完成
真实写入验证；其他游戏类型仍需按其选项和服务端规则单独验证。

本轮运行时 IPC 与会话复用证据详见 `DD/runtime-ipc-test.md`。

可复核的脱敏中间报告位于 `DD/`。生产前端快照和客户端静态资源也仅保存在该目录，未包含登录凭证或账号响应。
