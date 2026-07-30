# 方案 A：稳定独立设备 DD sidecar

## 决策

Fupload 的 DD provider 采用稳定独立设备 sidecar 作为核心方案。Go 主程序启动 DD
自带 `netease_dd.exe` 执行 Python 适配层；sidecar 使用固定 `clientNo` 建立独立
设备会话，因此可以与 DD GUI 同时在线，不需要 WebView2/CDP 或进程注入。

## 设备状态

设备状态保存在 `DD/sidecar-device.json`：

```json
{"client_no":"<32 hex characters>","version":1}
```

`clientNo` 不是账号凭据，也不能用于直接登录，但必须稳定复用。实现要求：

- 首次安装生成一次，后续只读复用。
- 在原生 DI 容器初始化前设置 `datacenter.local_data.machine_data.clientNo`。
- 文件存在但格式错误时拒绝启动，不静默生成新值。
- 文件丢失时提示用户确认后再重建设备，避免网易侧出现大量设备记录。
- 不把 GUI DD 的 `QSettings(Netease/CC/client_no)` 作为 sidecar 标识。

`eid` 是服务端分配的会话端点标识，不是持久设备 ID。同一 `clientNo` 连续两次登录
返回了不同 `eid`，因此不能用 `eid` 变化判断设备是否变化。

## 运行链路

```text
Go
 -> 启动单例 sidecar
 -> sidecar 加载固定 clientNo
 -> AccountCredStorage 解密 cred.db
 -> MobileReLoginFlow 建立独立设备会话
 -> JwtHelper 获取 loginToken/JWT
 -> 频道历史 transport
 -> LoginController 内存 Cookie + UiApiClient + NepWrapper
 -> 作者接口 transport
```

Go 与 sidecar 使用 JSONL stdin/stdout 或当前用户 Named Pipe。凭据、Cookie、JWT、
`x-w163-token` 和 signed URL 不跨 IPC；sidecar 执行请求，只返回业务字段和脱敏错误。

## 实测证据

测试时 GUI DD PID `40908` 保持运行并正常登录：

- 独立设备 sidecar 登录和 JWT 成功。
- `channelId=10075340` 最近 3 小时拉取 1 页、7 条消息。
- `/login/dflogin` 和 `/server/ts` 成功。
- `/addon/create`、`/addon/modify`、`/share/create`、`/share/modify`、
  `/wa/create`、`/wa/modify` 均成功生成 POST 签名，`request_sent=false`。
- 并发会话保持 30 秒后正常退出，GUI DD 未被顶下线。
- 第二次运行读取同一状态文件，`state_created=false`；没有生成新 `clientNo`。
- `cred.db` 未被 sidecar 改写。
- 后续串行真实写入中，六个作者 create/modify 均返回 `code=0`，插件 PUT 上传为 200。

## 进程与更新

- Go 必须保证每个用户只有一个 sidecar 实例。
- sidecar 直接运行 `100128/netease_dd.exe`，不调用需要管理员权限的 `Start.exe`。
- 正常 DD 更新仍由用户启动 `Start.exe` 完成。
- sidecar 启动时校验 DD 版本和必要资源；版本不匹配时拒绝运行并提示重新验证。
- sidecar 崩溃后可以使用同一 `clientNo` 重启，不创建新设备身份。

## 写操作边界

最初并发验证只生成作者 POST 签名；后续完整 builder 已完成真实 CRUD，详见
`author-crud-verification.md`。实施顺序：

1. `session doctor`、JWT 刷新和 sidecar 单例。
2. 频道解析与 A/B 历史拉取。
3. 作者列表/详情和 create/modify dry-run。
4. 资源专用字段校验、文件上传和显式确认后的真实写入。

真实测试还确认 sidecar 必须单例：两个相同 `clientNo` 的 sidecar 同时登录时，后启
会话可能无法取得 JWT。该限制不影响 GUI DD 与一个 sidecar 并存。
