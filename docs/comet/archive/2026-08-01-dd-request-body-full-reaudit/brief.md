# Outcome

重新完整审计并修复 DD 插件、配置、WA 发布链路，目标不是只修一个 422 个例，而是逐动作、逐字段、逐依赖、逐错误阶段重新对齐官方网页/客户端行为。最终交付必须让 Agent 有足够证据相信：可覆盖字段不会再因为明显错传、漏传、父子依赖失效、旧记录投影误用、上传 descriptor 错误或错误体丢失而产生不可解释的 4xx/422。

# Scope

- DD 插件、配置、WA 的 create/update/edit/delete 全链路重新审计。
- 覆盖字段 allowlist、create-only/update-only/edit-only 锁、公共商业字段、频道、关联、VIP、配置备份/WTF/WA 选择、WA 解析与版本、上传授权和对象 PUT。
- 重新检查当前 Python builder、schema、sidecar、readback、日志、Skill/reference/README 与 canonical spec 的一致性。
- 在 `analyze/` 生成本轮完整报告，记录官方证据、字段矩阵、发现的问题、修复、命令结果、真实/模拟错误请求体证据、残余风险；`analyze/` 保持不跟踪。
- 对 DD 官方 HTTP/业务拒绝，确保保留脱敏后的实际请求 JSON/body、响应 JSON/body、HTTP status、业务码、字段提示、截断状态和 log_path；本轮要用测试或受控探针把错误请求体抓回来作为证据。
- 重新运行可行的 live/read/write 验证；探索赛季继续按用户既有约束排除 live 写入。

# Non-goals

- 不发布或保留正式业务对象；所有 live 临时对象必须按精确 SN 清理。
- 不修改 DD 官方客户端二进制、凭据库、Cookie、GUI 进程内存或服务端下发命令。
- 不把 token、Cookie、JWT、clientNo、signed URL、原始 WA、原始备份、认证目录内容或未脱敏请求体写入 Git、publish、CLI 输出或 Comet 报告。
- 不重做 NewBeeBox 官方 CLI 或第三方 NewBeeBox 对齐，除非 DD 共享代码被本轮修改影响。
- 不对探索赛季执行 live 写入。

# Acceptance examples

- 对 plugin/config/WA 每个 create/update/edit/delete，报告能列出请求字段、动作可写性、来源、父依赖、默认/保留/清空语义、上传 descriptor、readback 证据和测试覆盖；不能以“上次通过”替代本轮审计。
- 至少一个受控 DD HTTP/业务拒绝或等价 sidecar HTTPError fixture 证明错误日志包含同一次调用的脱敏 request body、response body、HTTP status、原生业务 code、字段/校验提示、endpoint、stage、byte/truncation 元数据，且 CLI 只返回安全摘要和 log_path。
- 如果发现会导致 422/403/假成功/verification_required 错误归类的字段问题，必须修在 schema/builder/sidecar/readback 的根因位置，并增加回归测试。
- 真实或受控验证覆盖全部非探索赛季 build 的只读依赖图，并覆盖 plugin/config/WA 的安全 create/update/edit/delete 或明确解释因环境限制跳过的 live 写入；任何跳过项不能写成通过。
- publish 证据目录只保存脱敏计划、输出和验证摘要；analyze 报告保存详细审计但不进入 Git；敏感扫描不命中真实凭据、signed URL、clientNo、原始 WA 或原始备份。
- Comet Verify 报告逐项引用本轮代码、测试、docs、publish 证据和 analyze 报告位置；Archive 前单测、compileall、diff check 和 Comet check 均通过或记录诚实失败。

# Constraints and invariants

- 使用当前官方 DD 安装和 Python CLI，不引入 Go 方案、浏览器自动化或手写直连 HTTP 替代官方 sidecar 链路。
- 所有 DD live 操作复用一个 task session，串行执行，任务结束必须 stop，cleanup_complete 必须可验证。
- 明确 HTTP/业务拒绝为 verification_required=false；PUT/mutation 连接不确定或 accepted-write 读回不确定才为 true。
- 错误日志必须递归脱敏，结构化 JSON 和截断非 JSON 文本都要覆盖；falsy 业务码 0 不能丢。
- 上游父选择变化必须废弃下游 selector；Python 在写入前重新 GET 并验证 selector provenance。
- 旧记录缺字段时不能注入 create 默认、null 或猜测值绕过官方 validator；缺字段属于其他 action 时要前置正确动作或停止。
- 所有 claims 必须由当前文件、命令输出、测试、publish 证据或 analyze 报告支撑。

# Decisions

- 本轮 change 名称：`dd-request-body-full-reaudit`。
- 继续排除探索赛季 live 写入，符合用户先前明确约束。
- 错误请求体证据优先用安全的受控 fixture/HTTPError 旁路和不产生副作用的拒绝探针；只有能证明不会保留业务对象时才执行 live negative mutation。
- `analyze/` 用于详细探索报告和中间材料，不加入 Git；Comet/report 只引用报告路径和摘要。

# Open questions

None. 用户目标已经要求开 change 修复并持续执行到足够自信；当前 scope 中没有需要用户新增决定的业务分支。

# Verification expectations

- 运行 `python -m unittest discover -s fupload\scripts\tests -v`。
- 运行 `python -m compileall -q fupload\scripts`。
- 运行 `git diff --check`。
- 运行 `comet native check dd-request-body-full-reaudit`。
- 运行 DD doctor、单 session read matrix、必要 live write matrix、错误请求体捕获验证和敏感扫描。
- Verify 报告必须包含 Commands and results、Skipped checks、Spec consistency、Known limitations and risks、Conclusion 和 canonical acceptance evidence block。
