# Fupload Python CLI 完整目标规格

## 交付和命令面

唯一可分发产物为仓库根目录 `fupload/` Skill；原子 CLI 是 `fupload/scripts/` 内纯 Python 项目，不含 Go 源码或编译二进制。平台一级命令为 `newbee` 与 `dd`。插件、配置、WA 均公开：

- `create|update|edit|delete`
- `list|get`
- 资源专用分类、版本、备份、日志、上传、引用或分享码等只读/附属命令

create 建立主对象，update 更新版本/备份内容/WA 内容，edit 按资源官方 allowlist 修改设置，delete 删除一个明确目标。底层共用 modify endpoint 不改变动作白名单。每级命令和叶子命令都有 help，Skill 调用统一使用 JSON 输出。

## DD session 命令

DD 增加 `session doctor|start|status|stop`。doctor/status 是本地只读操作，不登录。start 需要 `--confirm-close-gui`，关闭身份和签名复验通过的官方 GUI 后启动一个 task broker，并返回 opaque `session_id`。普通 DD 远端命令必须通过显式 `--session <id>` 连接，缺失、失效或属于另一用户的 session 在网络前失败。

broker 持有唯一 sidecar 和一次原生登录，串行执行命令。每个请求含唯一 request ID，响应按 ID 匹配，不能依赖 stdout 到达顺序。stop 和 broker `finally` 走官方 logout/event-pump/DI shutdown；十分钟 idle timeout 只负责回收遗留 session。CLI 输出不含进程控制句柄、凭据或 clientNo。

## JSON 输入模型

所有写命令只接受 `--input <path|->` 的版本化 JSON；`-` 从 stdin 读取一个文档。schema 拒绝未知字段，并标注 required、optional、conditional、create-only、update-only、edit-only、read-only。解析保留“字段省略”和显式 `null/false/0/[]/""` 的差异：update/edit 省略表示保留，显式空值只在该字段允许清空时清空。

网页表单中的全部业务字段都进入 schema、help 和 reference，并标注每个动作的 allowlist。前端默认值不是 CLI 默认值；只允许固定协议常量、分页、超时和输出格式等技术默认。create-only 或当前 SN 后锁定字段出现在 update/edit 时，在任何网络写入前按 JSON path 拒绝。

session ID 属于命令执行上下文，不写进可发布业务 JSON。最终 JSON 不嵌入 GET 的完整响应、signed URL、凭据或原始备份对象；动态值只保存父字段及稳定 ID/opaque selector。

## GET 驱动的 JSON 生成

CLI 为每种资源声明机器可读依赖图。Skill 先调用只读叶子命令，按以下顺序收敛选择：

1. create 读取顶层 options；update/edit/delete 先 GET 当前目标，以远端锁定字段为父上下文。
2. 用户选父项后再调用带父参数的子项 GET。
3. GET 输出 `items` 中只含稳定值、显示元数据和必要父引用；需要下一层时返回依赖说明。
4. 父项改变后，调用方必须清空全部 descendants 并重新 GET。
5. 依赖闭合后，调用方生成一次最终业务 JSON 并保存到发布目录。

不要求用户手工拼接后台对象，也不提供“任意 JSON 透传”逃生口。配置依赖至少覆盖 backup、WTF account/server/role、account-scoped WA 和 retail selector；插件覆盖 game type/version 与两级分类；公共字段覆盖 scope 条件、outer free/paid mode、付费方式及参数、room/channel、关联候选和 VIP；WA 覆盖 game type/category 与材质开关/路径。

已有对象必须先从 GET 派生 `usage_mode = paid if need_buy || need_anchor_vip else free`。该展示态不进入 wire JSON；update/edit 不能直接改变 outer mode，但 paid 模式下仍可修改两个付费方式子开关及其条件参数。Python 应比较应用官方条件归一化前后的 live mode，不能把 `need_buy`/`need_anchor_vip` 误标成整体 create-only。

## 写入前 read-modify-write

每个写命令在 broker 内按固定顺序执行：

1. GET 目标详情并确认所有权、存在状态和当前锁定字段；create 跳过目标详情。作者列表仅作存在/所有权交叉核对，不能以 DD 两个读模型的异构时间戳阻塞合法写入。
2. 从最终 JSON 的父字段重新 GET 全部动态依赖。
3. 验证每个子 ID/selector 的父归属、当前可用性、唯一性、数量限制和 selector provenance。
4. 将详情转换为资源专用 form model，按字段存在性应用输入和条件清空。
5. 从最新 GET 恢复完整对象，使用资源和动作专用 allowlist builder 生成 wire payload。
6. 完成本地文件校验、上传授权与对象 PUT。
7. 调用 mutation。
8. 通过详情、列表或版本接口读回关键字段。

步骤 1-5 任一失败时上传数和 mutation 数必须为零。禁止把 GET map 原样 update 后 POST；作者、审核、统计、临时 URL、哈希和 raw backup 字段不得进入 payload。

## 文件和上传抽象

上传 descriptor 必须显式区分 `file_name=fixed`、`file_name=empty` 与 `file_name=omitted`，`None` 不得隐式变成本地 basename。每个 descriptor 固定扩展名、确定性 MIME、业务类型、前端大小限制、授权参数和 PUT headers，并在授权后校验服务端 `maxSize`。

signed URL 是不透明字符串，只能原样传给 PUT。URL 及 query 不能解析后重组、unquote、quote 或二次编码。上传错误分别归属 authorize 与 object_put；授权失败不得 PUT，PUT 非 200 不得 mutation。

## 输出和错误

稳定输出顶层包含 `schema`、`platform`、`operation`、`success`、`data|error`。错误包含 `stage`、`kind`、脱敏 `endpoint`、可选 `http_status`、`business_code` 和 `verification_required`。明确 HTTP/业务拒绝、登录/GET/schema/归属校验失败为 false；只有结果不确定的 PUT/mutation 或 accepted write 后 readback 不确定为 true。

不得输出 access/refresh/resource/Creator token、device proof、Cookie、JWT、登录 code、clientNo、signed URL、原始 WA、raw backup 或完整 write payload。错误消息中的 URL 先降为固定 endpoint 名称；sidecar stderr/stdout 同样经过结构化脱敏。

`--dry-run` 只验证 schema、本地文件和无须远端的规则，不创建 session、不登录、不上传、不宣称动态 ID 或权限有效。真实远端预检通过普通写命令执行，但 mutation 前的验证结果可以在失败响应中安全呈现。

## 删除和不确定结果

delete JSON 必须包含目标 ID、资源类型和显式 `confirm_delete=true`，拒绝额外可修改字段。执行前 GET 目标并验证当前作者所有权；mutation 后 GET/list 验证不存在。超时或连接中断时返回 `verification_required=true` 并只提示读回，不能自动重发 delete。

create 成功而后续步骤失败时返回已创建 ID、最后确定阶段和最小恢复入口，不重复 create。所有写操作遇到不确定结果一律先读回；重复版本和相同对象的保护使用 live detail/version，不只依赖本地缓存。

## 信任边界

NewBee 生产 origin 与认证目录保持源码固定，测试通过 adapter/mock 注入，不通过生产环境变量改写。携带凭据或本地文件的请求在发送前验证 HTTPS、host 和 port；任何跨 scheme/host/port 重定向在重发 header/body 前失败。

NewBee 认证目录和 DD 状态目录由 Windows Known Folder 派生；目录链含 reparse point 或逃出受信用户目录时 fail closed。DD binary 启动前验证 Authenticode 链和官方组织发布者身份。

## Skill 仓库边界与发布记录

产品代码、help、schema、references 和 README 位于 `fupload/`。拆包、反编译、探针和探索报告位于 ignored `analyze/`。Git 不跟踪 Go、EXE、客户端拆包、运行缓存、设备状态或凭据。

每次发布的最终 JSON 位于被发布项目根目录 `publish/<YYYYMMDD-HHmmss>-<platform>-<resource>-<action>/`，不放在 Skill 目录外侧或 Skill 内。独立发布创建新目录；同一计划的重试、读回和清理记录复用原目录。

## 验证

单元/合同测试覆盖全部 schema 字段、动作锁、显式空值、依赖图、父切换、跨父 selector、分页、上传 descriptor、特殊文件名、错误分类、脱敏和 readback。进程测试用可计数 fake runtime 验证一次 task 一次 login、GUI 未确认时零 login、并发串行和 logout。

真实验证动态枚举两个平台当时全部支持 build；DD 排除探索赛季。插件、配置、WA 分别执行 create/update/edit/delete 与读回，每个 CLI 叶子接口记录真实通过、预期拒绝或明确限制。修复 finding 后重跑最小相关测试和全量回归。
