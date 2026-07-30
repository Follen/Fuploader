# DD 运行时 IPC 与会话复用实测

调研日期：2026-07-30

## 测试边界

- 复用已运行、已登录的 `netease_dd` 主进程，测试时 PID 为 `12504`。
- 全程未关闭或重启 DD，未使用 UI 自动化完成测试。
- 未发送频道消息，未调用插件或配置的创建、修改、发布、删除接口。
- 未输出或保存 Cookie、登录 token、JWT、`x-w163-token`、signed URL。

## 本机 IPC 结论

当前版本没有向本机第三方程序暴露通用的聊天历史或 WebView 调用 IPC：

- 可见 Qt LocalSocket 只有 Overlay 管道，不承载聊天历史或作者操作。
- `WM_COPYDATA` 只处理客户端 URL action，不提供任意 HTTP/JavaScript 调用。
- `components.remote_cmd` 内置了 `web exec-js` 等 CLI 命令，但入口是网易服务端下发的 `SID_DDCLAUDE`、`CID_DDCLAUDE_CALLBACK`/`CID_DDCLAUDE_REPORT`，不是本机监听端口或命名管道。
- 当前 WebView2 实例未开启 DevTools TCP/pipe；旧 `cef_web_service_cache` 下的 `DevToolsActivePort` 是过期文件，与当前进程无关。

因此，Go 程序不能直接向当前 DD 进程发送 `web exec-js` 或“拉历史消息”命令。把远程命令协议伪装成本机 IPC也不可行，它依赖 DD 已登录的服务端消息连接。

## 当前会话的只读证据

主进程日志能够证明两套会话都在工作：

1. 频道侧 JWT 在登录后换取成功，并在过期后由主进程自动刷新。
2. 作者侧完成 `/login/dflogin`，随后通过 `nepHttpGetSignedUrl` 对作者请求签名。
3. 已成功触发作者只读路径：`/addon/addon_list`、`/addon/detail`、`/share/list`。

这确认当前登录态可访问插件/配置作者数据，且不会影响客户端登录态。日志中没有 `nepHttpPostSignedUrl` 记录，因此本次不能把“页面上存在发布/修改入口”表述为“本机 IPC 已打通写操作”。

## 目标频道样本

主进程已经对 `channelId=10075340` 请求过历史消息：

- 一页 30 条，`msgId` 范围 `30323..30352`。
- 随后收到并解析到 `30353..30359`。
- 日志只记录分页范围、消息数量、审核通知和已读位置，不记录消息正文、作者与 `sendTime`。

所以可以确认历史拉取在 DD 主进程内正常，但无法仅靠现有本机 IPC/脱敏日志导出“最近 3 小时正文”。

## WebView2/CDP 实测结论

受控重启并增加 WebView2 调试参数的方案已经测试失败：没有形成可连接的 DevTools
TCP/pipe，且该次启动 DD 界面未正常出现。因此 CDP 不再作为当前版本的实现候选。
在不修改或注入 DD 主进程的前提下，现有 GUI 会话没有可供 Go 程序调用的本机代理。

## 后续无头验证补充

之后在 DD 保持打开时，使用 DD 自带 Python 运行时直接初始化原生模块，验证了
持久凭据解密、频道 JWT、最近三小时历史拉取（7 条）以及作者侧 NEP 签名 dry-run。
这条链路没有使用日志、浏览器 Cookie 文件或进程内存提取凭据，也没有发送消息或
作者写请求。

早期测试复用了 GUI DD 的设备身份，因此出现同设备会话冲突。后续为 sidecar 设置
独立且固定的 `clientNo` 后重新验证：GUI DD 与 sidecar 可同时在线，sidecar 完成
JWT、频道历史和作者签名，保持 30 秒后退出，GUI 未被顶下线。

因此无需让 Go 调用 GUI 的本机 IPC。核心方案改为稳定独立设备 sidecar；现有 IPC
和 CDP 结论仍成立，但它们不再阻塞 DD provider 实现。
