# Outcome

重新完成 DD Python provider 与当前官方网页及官方原生客户端的全量业务对齐审计，并修复本轮发现的全部偏差。最终结论必须由逐字段/逐动作矩阵、官方源码与反编译证据、合同测试、静态检查、真实单会话矩阵和真实错误请求体日志共同证明，不能因为上一轮已通过而跳过重新审计。

# Scope

- 重新提取插件、配置、WA 的 create/update/edit/delete：页面初值、编辑器打开投影、父子联动、校验、最终 JSON builder、上传授权、对象 PUT、mutation、读回和删除读回。
- 对每个 wire 字段记录字段名、JSON 类型、来源、动作、create 默认、存量省略/null/false/0/空字符串/空数组语义、父依赖、条件清空、endpoint 和读回投影。
- 独立复核官方网页 bundle、当前官方原生客户端 disassembly、Python transport、broker、sidecar、CLI schema/help、Skill/reference 和现有 publish/analyze 证据；上一轮报告只能作为线索，不能作为本轮完成证明。
- 全量审计错误链：在 DD 安装目录 `Fupload/logs` 保存失败调用的实际脱敏 request JSON/body、response JSON/body、HTTP 状态、原生业务码、字段校验提示、原始字节数和截断状态；特别验证 4xx/422 与 HTTPError body 的捕获没有改变官方异常控制流。
- 真实验证覆盖当前动态返回的所有非探索赛季 build 只读依赖图，以及具备依赖的隔离 plugin/config/WA create/update/edit/delete/readback；任务串行且只登录一次，结束退出并清理所有临时 SN。
- 复审报告写入被 Git ignore 的 `analyze/`；最终实现、测试、Skill/reference、canonical 规格、publish 证据和 Comet 产物按项目规则处理。

# Non-goals

- 不做探索赛季真实写验证。
- 不修改用户已有正式对象；真实写只使用带唯一名称的隔离私有对象并按 SN 清理。
- 不自动重发已经发送但读回不确定的 mutation。
- 不记录或提交 Token、Cookie、JWT、clientNo、签名、signed URL credential、原始 WA 或完整 raw backup。

# Acceptance examples

- 逐动作矩阵能把每个 mutation 字段映射到官方源码证据、Python builder、schema allowlist 和至少一个回归测试；矩阵没有只凭“成功”推断的空白字段。
- plugin/config/WA 的 detail、author/list、版本历史和 backup read model 的职责被明确区分；任何父选择、selector provenance、分页和旧记录缺失字段错误都在上传前确定失败。
- 每个 create/update/edit/delete 真实操作后都有对应 detail/list/version/delete readback；读模型延迟只触发有界 GET-only poll，绝不重发写请求。
- 对真实或模拟的 4xx/422，日志包含同一次调用的实际脱敏请求 body 和服务端响应 body、HTTP status、业务码、字段提示、byte/truncation 元数据；敏感值不出现在日志、CLI、report 或 publish。
- 最终真实矩阵在一个 DD login session 内完成全部可行资源动作，`login_count=1`、GUI 冲突状态符合合同、stop/logout 成功、临时对象全部不存在。

# Constraints and invariants

- 官方网页最终 builder 和原生 client transport 是 wire 契约；不能以通用默认、truthiness、详情透传或单一 read model 替代资源/动作专属逻辑。
- 所有写入先完成 live GET、归属校验、父子 selector 校验和 schema 验证，再上传或 mutation。
- 列表必须按真实分页读取；重复页、分页上限或必需候选为空时 fail closed。
- 明确 HTTP/业务拒绝为确定失败；连接不确定或 accepted-write readback 不确定为 `verification_required=true`，不自动 replay。
- DD GUI 正在运行时，关闭前必须有用户明确同意；doctor 不登录；一次任务只创建一个 sidecar/login。
- 错误日志独立限制 request/response UTF-8 byte，递归脱敏并恢复官方 HTTPError read bytes。

# Decisions

- 2026-08-01：本轮新建独立 Native change；上一轮归档结果不作为本轮全量对齐证明。
- 2026-08-01：探索赛季继续排除真实写验证；所有真实对象必须隔离并清理。
- 2026-08-01：用户要求直接进入复审和修复，不等待额外的 Shape 讨论。

# Open questions

# Verification expectations

- 重新运行官方证据定位和静态字段矩阵审计，保留准确文件/行号或 disassembly 符号。
- 运行 `python -m unittest discover -s fupload\scripts\tests -v`、`python -m compileall -q fupload\scripts`、`git diff --check` 和 `dd session doctor`。
- 真实读取所有非探索 build 的 game versions、category、association、author list、backup、WA options，并保存不含凭据的 publish JSON。
- 真实执行隔离 plugin/config/WA 全动作矩阵，保存每一步输入、输出、退出码、读回、清理和 session 计数。
- 在最终报告中逐项列出未发现、发现并修复、跳过及残余限制；只有没有未解释 finding 且所有验收项有直接证据时才能 Verify pass。
