# Outcome

让显式选择第三方 Python 通道的 NewBeeBox 插件、配置分享和 WA 发布流程，与 Creator Center 网页的实际接口、表单状态机和读回行为逐项对齐。网页网络请求、动态 GET、字段默认值、父子联动、阶段锁、明确错误与不确定结果是唯一业务基准；`ncc` 只用于辅助交叉核对，不能限制网页支持的字段或动作。

# Scope

- 审计 Creator Center 网页的插件、配置、WA create/update/edit/delete 全链路：初始化和动态 GET、请求 URL/方法、payload、上传、默认值、条件清空、禁用/锁定字段、审核/可见性和读回投影。
- 逐字段比对网页表单、网页 wire payload、现有 Python schema/builder/readback；以网页的实际行为为准修复缺失字段、错误字段名/类型、错误默认值、错误保留/清空语义和服务端静默忽略字段。
- 覆盖插件版本与 build 绑定、媒体与附件、配置云备份及依赖选择、WA 原始字符串的脱敏 readback、商业/订阅/价格/有效期、审核/公开状态和插件/配置关联频道。
- 将网页控件依赖改写成 Python 的显式 GET 依赖图：先读父项与当前详情，校验子项归属后才生成一次最终 JSON；写入前重复必要 GET，拒绝过期或跨父选择。
- 使用网页接口及网页读模型完成私有临时对象的插件、配置、WA create/update/edit/delete 实测，覆盖支持的 build；每个对象在验证后仅按本次记录的 ID 清理。
- 更新 Python CLI 的 schema/help、Fupload Skill、NewBee reference、README、合同测试和受跟踪 `publish/` 验证记录；官方 CLI 选择策略保持不变。

# Non-goals

- 不改变 NewBeeBox 默认优先官方 `ncc` 的渠道选择，也不以 `ncc` 的可用选项推断网页协议。
- 不实现 Creator Center 的帖子、评论、社区、下载、账户、消息或网页 GUI 自动化。
- 不读取/复制官方 CLI 凭据文件，不接收或记录 token、cookie、签名 URL、原始 WA 字符串或原始云备份内容。
- 不对探索赛季做真实写入验证；不删除任何验证计划外的线上对象。

# Acceptance examples

- 网页插件 create 的初始默认/隐藏字段与 Python create payload 相同；网页禁用的已有对象字段不会出现在 Python edit JSON，网页仍允许的字段不会被 Python 误判为 create-only。
- 网页配置更换云备份、角色或父级内容选择时，下游插件/素材/字体/WA/角色选择被清空并重新 GET；Python 在任何上传或 mutation 前拒绝跨备份、过期或不属于父项的选择。
- 网页 WA create/update/edit 的分类、图片、附件、版本、商业和频道字段在 Python 中按相同 wire 类型、默认/清空语义和读回投影工作；原始字符串只以长度和摘要参与验证。
- 明确 HTTP/业务拒绝保留 endpoint、status/业务码并设置 `verification_required=false`；超时、断连和已接受写入后的网页读回不确定设置 true，且不自动重发。
- 用网页 API 真实创建的私有插件、配置和 WA 分别完成 create/update/edit/delete 与网页读回；插件版本使用支持的精确 build 字符串，探索赛季不写入。
- Fupload Skill、CLI `--help`、JSON schema 和 NewBee reference 对每个网页可写字段的路径、类型、阶段、条件、动态来源、默认/清空语义及读回字段可追踪一致。

# Constraints and invariants

- 网页抓取记录、拆包材料和探针仅放在忽略的 `analyze/`；可执行契约、代码、测试、Skill/reference、Comet 规格和脱敏发布记录必须在受跟踪范围。
- 所有 Python 写入都先 GET 当前对象和必要动态选项；现有对象从最新网页 detail 重建完整 wire payload，禁止透传网页只读、统计、审核和临时字段。
- 父项变化使全部下游选择失效。输入 JSON 只持久化稳定 ID、selector 或本地文件路径，绝不复制网页返回的完整对象。
- 文件上传沿用网页授权、文件名、MIME、大小限制、hash、header 和后续业务字段；对象上传成功不代表业务 mutation 成功。
- 每个写步骤串行执行并立刻用网页 detail/list/version 读回。结果不确定时先只读核对，不自动重发或扩大清理范围。
- NewBee API/认证/上传 origin 继续固定为受信 HTTPS origin，环境变量不得重定向凭据或请求目标。

# Decisions

- 2026-08-01：Python NewBeeBox 通道以 Creator Center 网页接口和表单行为作为唯一业务基准；`ncc` 仅是辅助证据。
- 2026-08-01：对齐范围覆盖现有发布域的插件、配置分享、WA 三类主记录及 create/update/edit/delete，不扩展社区或其他 Creator Center 产品域。
- 2026-08-01：真实验证继续使用明确命名的私有临时对象，逐个读回并按记录 ID 清理；探索赛季保持非目标。
- 2026-08-01：既有官方 CLI 默认优先规则保持不变；只有用户显式选择第三方 Python 管理工具时才使用本次对齐后的 provider。
- 2026-08-01：用户确认以网页为唯一业务基准的完整范围、验收、非目标和验证方式，可进入 Build。

# Open questions

- 无。

# Verification expectations

- 从网页脚本、网络请求和真实只读响应建立端点/方法/字段/默认值/依赖/阶段锁/读回矩阵；每一项由可复核网页证据或真实探针支持。
- 合同和单元测试覆盖全部三资源字段、动态父子切换、缺失/过期选项、网页默认值、显式清空、静默忽略、上传错误、业务拒绝、超时和延迟读回。
- 在当前网页登录环境中，对三类明确命名私有对象执行完整 create/update/edit/delete 矩阵和网页读回；验证记录不含敏感内容且清理仅限该次 ID。
- 运行完整 Python 测试、编译、`git diff --check`、CLI help/schema/reference 追踪审计及敏感输出扫描。
