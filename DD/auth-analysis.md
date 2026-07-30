# 网易 DD 登录态与请求签名分析

## 两套鉴权链路

作者中心和频道消息不是同一套鉴权，不能用一个 Cookie 或 token 覆盖全部能力。

| 用途 | API 主机 | 鉴权方式 | 结论等级 |
| --- | --- | --- | --- |
| 插件、配置分享、WA 作者接口 | `uiapi.w.163.com` | UIBox token + 时间戳 + 客户端 NEP 签名 URL | 生产前端静态确认 |
| 空间频道和消息历史 | `api.cc.163.com` | 登录 token 换取短期 JWT，随后使用 `Authentication` 请求头 | 客户端静态及运行时确认 |

## UIBox 作者接口

嵌入页通过 User-Agent 中的 `NeteaseUIClient` 或 `app/df_client` 判断客户端环境。

登录与请求过程：

1. 对 `GET /login/dflogin` 发起客户端签名请求。
2. 响应返回 UIBox 用户信息和 token。
3. 前端把 token 放入 Axios 默认请求头 `x-w163-token`。
4. 每次业务请求前取得客户端/服务端时间戳并设置 `x-timestamp`。
5. GET 请求调用 `window.jsBridge.nepHttpGetSignedUrl`。
6. POST 请求先序列化 JSON，再调用 `window.jsBridge.nepHttpPostSignedUrl`。
7. Bridge 返回 `signedUrl`，前端才向该 URL 发出实际 HTTP 请求。

这意味着仅回放浏览器 Cookie 不足以稳定调用作者接口。方案 A 直接复用 DD 随附的 `UiApiClient` 和 `NepWrapper` 完成作者登录、时间同步与 NEP 签名，不依赖 GUI WebView bridge，也不自行复刻 NEP 算法。

## 频道消息 JWT

客户端掌握 `uid`、`eid`、`loginToken`、`timestamp` 和 `appId` 后，先计算：

```text
MD5(appId + "_" + timestamp + "_" + loginToken)
```

然后请求：

```http
GET https://api.cc.163.com/v1/jwt?uid=<uid>&eid=<eid>&appid=<appId>&timestamp=<timestamp>
Authentication: <md5 seed>
```

响应 code 为 `OK` 时，从 `data.jwt` 取得 JWT。消息接口随后发送：

```http
Authentication: <jwt>
```

客户端 `JwtHelper` 的静态信息还显示：

- 登录 token 协议：`SID=44204`、`CID=8`。
- 默认 `appId`：`webcc`。
- 获取 JWT 最多重试 3 次。
- 遇到 `JWT_CLAIM_EXPIRED`、`UNAUTHORIZED` 或 `INVALID_TIMESTAMP` 时刷新 JWT。

## 实现边界

- 不把 `loginToken`、UIBox token、JWT 或 Cookie 写入配置、日志、命令行参数或调研文件。
- sidecar 应通过 DD 原生 `AccountCredStorage` 从 `cred.db` 解密自动登录凭据，并以稳定独立 `clientNo` 建立会话；解密结果和派生 token 只在内存中短暂使用。
- 作者 API 的签名绑定时间戳和请求内容，不能缓存 `signedUrl` 长期复用。
- 消息 JWT 要按服务端时间和错误码刷新；不要把 401 简单当成永久退出登录。
- 本文对应初始静态鉴权分析阶段，当时没有自动化登录或调用写接口；后续运行时
  验证和三次被 HTTP 422 拒绝的插件请求见 `stable-sidecar-plan.md` 与
  `author-field-coverage.md`。

## 无头运行时验证（2026-07-30）

在 DD 自带的 Python 3.7.17 运行时中，直接初始化原生 DI 容器并调用
`AccountCredStorage`、`MobileReLoginFlow`、`JwtHelper`，无需 GUI 控制即可完成：

```text
cred.db -> 原生 AccountCredStorage 解密 -> MobileReLoginFlow
       -> SID 44204/CID 8 -> JwtHelper -> 频道 JWT
```

随后从同一无头登录控制器内存对象取得 Cookie 元组，交给客户端随附的
`cli_anything.ccvoicehub.core.ui_api_client.UiApiClient`，`/login/dflogin` 和
`/server/ts` 均成功。作者侧插件、配置分享、WA 的 create/modify 六个端点均
成功生成 NEP POST signed URL；探针明确没有发送这些 POST，也没有输出 token、
Cookie 或 signed URL。

早期探针复用本机 DD 的默认设备身份时，GUI 会话曾退出；这只能证明同设备身份
重复登录存在冲突，不能推导为账号不支持多端。客户端源码确认持久设备标识是
`QSettings(Netease/CC/client_no)` 中的 `clientNo`，而 JWT 参数中的 `eid` 是登录后
服务端返回的会话端点标识。

最终方案为 sidecar 分配独立且固定的 `clientNo`，在 DI 容器初始化前注入。受控
并发测试中，GUI DD 保持登录，sidecar 同时完成 JWT、频道历史、作者登录和六个
POST 签名 dry-run，未发生顶号。第二次运行复用同一状态文件且没有生成新
`clientNo`；两次 `eid` 不同，进一步说明 `eid` 不应作为持久设备身份判断依据。

稳定设备状态位于 `DD/sidecar-device.json`。它不包含账号凭据，但必须避免每次
重建；文件损坏或丢失时应要求用户确认，不能静默生成大量设备身份。
