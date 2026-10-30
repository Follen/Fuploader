# 网易 DD 操作

完整字段、选择器、条件和接口映射见[平台字段总表](platform-fields.md#dd)。本文件保留会话与执行顺序。

## 一个任务复用一个会话

1. `dd session doctor`：检查官方安装和 GUI 状态，不执行登录。
2. `dd session start`：返回 session_id。
3. 任务内全部查询、写入及读回使用同一个 `--session <id>`，串行执行。
4. 在 `finally` 中执行 `dd session stop --session <id>`，要求 cleanup_complete=true。

GUI 正在运行时，只借用现有网页会话，native_login_count=0；不关闭客户端，不另开桌面登录。复用失败直接停止。`--confirm-close-gui` 仅兼容旧调用，不执行关闭。GUI 未运行时才使用官方保存凭据的邮箱/手机号原生登录流程。

用户不需提供 DD 邮箱、手机号、密码或 Cookie；禁止凭账号文本猜登录方式。借用会话清理不请求账号退出。CC 频道 JWT 换取链尚未打通，当前借用模式不能发现频道；缺少有效候选时不构造房间/频道发布字段。

## 选择、提交和读回

先读 game-types、对应 build 与分类树。插件 primary/secondary 分类有父子关系，变更父项后重新选择子项。关联内容使用平台返回的 (act_type,sn)，VIP 与频道只在功能启用时查询。

配置依赖：`backup_sn -> backup detail -> WTF account/server/role -> 该账号的 WA`。输入稳定 selector/UID/名称，最终表单由程序重建；不要提交原始 WTF 或正式服 EditMode/CooldownManager 导入串。不同 *_ids 字段未必都是数字 ID，按总表的逐项说明填写。

已有对象先读详情及作者列表，再保留未指定的值。免费/付费外层模式在创建后锁定，scope 变化也不能绕过。旧对象缺少当下必填项时先补明确值，不用 null 或 create 默认值填补。

Logo、展示图、附件通过官方授权上传；上传成功不等于最终发布成功。每次写后核对目标字段。最终请求失败或读回不明时，先查询状态，不自动重复提交。原生/API 错误包含 stage、HTTP/业务码及脱敏日志位置时，只读取对应错误记录。

## 云备份

scan/generate 只操作明确选择的本地内容。upload/create 校验 bundle 与分组 ZIP 后走官方 pre_create、对象 PUT、finish_create，并读回。include_common、WTF 根文件和角色选择分开处理；包中不能混入未选择的账号/角色或公共配置。

删除先预览并完整核对自有配置分享引用，执行每项前重查；已关联、分页不完整或关联未知时禁止删除。只删除备份，不连带删除配置分享。

频道列表需要另一份 CC JWT。该可选操作仅对匹配的 DD 100130 使用只读运行时辅助；若 DD 由启动器以高权限运行，频道查询需要同用户管理员终端，频道关联写入需要同权限启动的 Fupload 任务会话。普通上传继续使用普通权限 Cookie 路径。缺失或过期的频道缓存直接报错，不重新登录客户端。
