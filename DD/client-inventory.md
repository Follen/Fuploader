# 网易 DD 客户端调研清单

调研日期：2026-07-30

## 范围与安全边界

本清单记录的是初始只读盘点阶段；该阶段没有创建、更新、发布、删除或发送任何
远端数据。后续字段调研曾发送三次被 HTTP 422 拒绝的插件请求，详见
`author-field-coverage.md`，没有产生远端变化。整个调研均未复制或保存 `cred.db`、
原始 Cookie、登录 token、JWT、账号日志或未脱敏接口响应。

## 本机客户端

- 观察到安装目录：`D:\Software\NetEaseDD\100122`、`D:\Software\NetEaseDD\100128`。
- 调研时运行进程为 `netease_dd`，观察到的 PID 为 `12504`；PID 只代表当时实例。
- 客户端主体是 Qt + Python 3.7，网页功能使用 WebView2。
- `ccvoicehub.res` 是 ZIP 兼容资源包。本次从 `100128` 提取到 `DD/client/ccvoicehub-100128/`，共 3318 个文件，其中 1099 个 `.pyc`。
- 与本次目标直接相关的静态证据包括：
  - `util/cgi/jwt_helper.pyc`
  - `components/room_module/room_text_chat_area/room_text_chat_area_controller.pyc`
  - `web/common/web_interface.pyc`
  - `DD/remote/uibox-dd.js`

## 用户数据位置

客户端用户数据位于 `C:\Users\follen\AppData\Roaming\CCVoiceHub`。该目录含 `cred.db`、设置、日志和 WebView 缓存，属于敏感数据源，只在本机只读核对，不进入调研目录。

## UI 实测

通过已登录且已打开的 DD 窗口只读确认：

- 展示空间号：`16888`
- 空间名：`露露缇娅的专属空间`
- 目标频道：`提问与反馈 至暗之夜`
- 内部 `teamId`：`144686`
- 内部 `channelId`：`10075340`
- 类型：文本频道
- 所属分类 ID：`G10150764`
- 所属分类名：`露露的插件包 | 提问与反馈`

没有在 UI 中点击发送、编辑或管理操作。

## 证据等级

- 运行时确认：安装/进程、示例空间和频道的内部 ID 映射、历史消息请求参数及分页方向。
- 生产静态确认：WebView 作者接口、字段构造、桥接签名流程。
- 客户端静态确认：JWT 交换逻辑、历史消息处理方法及消息字段。
- 尚未确认：任意展示空间号到 `teamId` 的通用解析接口；作者写接口的服务端必填字段和完整校验规则。
