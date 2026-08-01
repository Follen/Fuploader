# Outcome

建立 DD 插件、配置、WA 发布链路的逐字段、逐动作、逐状态 wire 回归体系。回归必须证明每个 CLI JSON 字段在 create/update/edit/delete 中的 schema 结果、依赖 GET、上传行为、最终 endpoint、最终请求体存在性/类型/值、条件清空、远端字段保留、mutation 次数、读回判据和错误日志，而不是只证明字段位于 allowlist 或某个综合对象成功提交。

本轮必须通过可维护的表驱动矩阵暴露并修复当前实现与官方网页/原生客户端行为之间的任何请求体差异，使后续新增字段或调整 builder 时，缺少逐字段 wire 用例会直接失败。

# Scope

- 资源：DD plugin、config、WA。
- 动作：create、update、edit、delete；共用 modify endpoint 的动作仍分别建模和验收。
- 输入矩阵：对每个动作允许字段覆盖 omitted、正常有效值、替代有效值，以及适用的 `false`、`0`、空字符串、空数组、官方支持的 `null`、上下边界、越界、非法类型、非法枚举、父项变化后旧子项、条件关闭但子字段仍存在。
- schema 层：逐 case 断言接受/拒绝、规范化结果、精确 JSON path 和 mutation 前停止。
- dependency 层：逐 case 断言必需 GET 的 endpoint/参数/顺序、条件关闭时跳过的 GET、selector provenance、备份/WTF/频道/VIP/关联/分类/build 依赖失效。
- upload 层：逐 case 断言是否上传、`/file/upload` descriptor、`file_name` 的固定/空字符串/省略三态、MIME、business ID、file type、本地上限、服务端上限、对象 PUT header、字节长度和 SHA-256。
- mutation 层：逐 case 捕获 `/addon/*`、`/share/*`、`/wa/*` 的最终 body，断言字段是否存在、精确 JSON 类型和值、保留字段、条件清空字段、应省略而非发送 null 的字段，以及 mutation 次数。
- readback 层：逐 case 断言使用的只读 projection、比较字段、轮询行为、成功/明确失败/不确定分类，且不重发 mutation。
- error/log 层：逐 case 断言阶段、HTTP 状态、原生业务码、字段提示、脱敏后的 request/response body、截断元数据和 `verification_required`。
- 生成 `fupload/scripts/tests/test_dd_wire_matrix.py` 或等价专用模块，并允许抽取测试 harness/纯 builder helper 到合适模块。
- 在不跟踪的 `analyze/dd-field-by-field-wire-regression-20260801.md` 生成完整字段清单，逐行映射 `resource/action/field/state -> test id -> endpoint/body expectation -> result`。
- 若矩阵发现生产差异，修复 schema、builder、dependency preflight、upload、readback 或日志根因并增加回归用例。

# Non-goals

- 不对探索赛季执行 live 写入。
- 不用单次 live 成功替代逐字段 deterministic wire 回归；live 只用于验证代表性真实合同和环境链路。
- 不为每个字段在真实账号创建业务对象；逐字段完整性主要由官方证据和捕获最终 wire body 的隔离 harness 验证。
- 不修改 DD 官方二进制、GUI、凭据、Cookie 或服务端数据结构。
- 不把 token、Cookie、JWT、clientNo、signed URL、原始 WA、原始备份或账号侧显示信息写入 Git。
- 不扩展 NewBeeBox 行为，除非共享代码被本轮 DD 修复直接影响。
- 不跟踪 `analyze/` 和现有 `publish/20260801-091500-dd-request-body-full-reaudit/`。

# Acceptance examples

- `plugin/create/name/normal`：schema 接受，最终 `/addon/create` body 中 `name` 为原字符串，且没有额外 mutation。
- `plugin/edit/description/present`：schema 在 `$.description` 拒绝，GET、上传和 mutation 均为零。
- `plugin/update/file/special-local-name`：先完成版本和依赖检查，再以固定 `addon.zip` 授权上传；PUT 字节和 SHA-256 与源文件一致；最终 `/addon/modify.detail_url` 使用 `d_url`，不发送本地 basename/path。
- `plugin/edit/jump_room=false+stale-channel`：不请求频道 endpoint，最终 body 清空 room/channel 并关闭 sync；当前其他商业字段完整保留。
- `config/update/backup_sn/changed`：遗漏任一七组、WTF 或 retail 重新选择时在对应 JSON path 拒绝且 mutation 为零；完整选择时重新 GET 新备份并只使用新 selector。
- `config/update/wtf_role_ids/changed`：省略 known/unknown WA 选择时最终 wire 清空两组，不保留旧账号的子项。
- `config/update/retail_ui_config/null`：仅在官方支持的语义下接受并生成相应省略/清空状态；其他 object 字段的 null 均按 schema 合同精确拒绝。
- `config/edit/need_buy=false+price_fen=0`：最终 `/share/modify` 保留官方允许的历史字段或归零，必须由矩阵明确断言，不能只断言请求成功。
- `wa/create/category_ids`：输入可接受 ID 经 builder 后最终 wire 全部为字符串，最多五项；非法类型和第六项分别在精确 path 拒绝。
- `wa/edit/content/unchanged-wa2`：仍调用一次 native parser，最终 body 使用本次解析 ID；parser 失败时 mutation 为零。
- `wa/edit/with_file=false`：不上传，最终 body 按官方 builder 保留既有 `file_path/file_install_path`，不擅自发送空值。
- 任意明确 HTTP 422：日志保留脱敏 request/response body、HTTP status、业务 code 和字段提示；CLI 返回安全摘要和 log_path，`verification_required=false`。
- 任意 mutation timeout：只发生一次 mutation，读回后分类为确认成功或 `verification_required=true`，绝不自动重传。
- delete：只提交官方 identifier body；confirm/schema/ownership 前置失败时 mutation 为零，成功后只读确认不存在。
- 报告中的每个允许字段至少有一个 wire-presence 用例，每个条件字段至少有 enabled/disabled/stale-child 用例，每个受限字段至少有拒绝用例；任何缺口使回归失败。

# Constraints and invariants

- 官方网页 submit builder、详情打开投影和官方客户端 transport 是目标合同；现有实现和现有测试不能反向定义官方行为。
- 测试清单必须从显式字段目录生成或由测试校验其与 schema/动作字段集合双向相等，新增/删除字段时不得静默漏测。
- 每个 case 必须有稳定 ID，失败输出包含 resource/action/field/state 和实际捕获调用，便于直接定位 422 风险。
- request-capture fake session 必须区分 GET、dependency POST、native parser、upload authorize、object PUT、mutation 和 readback，不能把所有调用压成一个 mock 返回值。
- preflight 拒绝必须证明上传次数和 mutation 次数为零；upload 前失败不能留下对象 PUT。
- create 默认只能作用于 create；update/edit 对遗漏字段必须从官方当前投影保留或按官方条件清空，不得注入 create 默认、null 或猜测值。
- 父项变化使旧子 selector 失效；每次写入都基于同 session 最新 GET 验证 provenance。
- `false`、`0`、空字符串、空数组、遗漏和 `null` 是不同状态，测试不得使用 truthiness 合并。
- final body 断言使用精确深度结构和 JSON 类型；仅 `assertIn(field)`、字段集合相等或 HTTP 2xx 不算 wire 行为覆盖。
- 真实 DD 操作继续使用一个 task session、串行执行、任务结束 stop；不并发启动多个 sidecar，不影响 GUI 环境。
- 错误日志递归脱敏，任何 fixture 中的模拟敏感值也必须验证不会原样出现。
- 测试和报告不依赖当前真实账号对象名称、SN、session ID 或凭据。

# Decisions

- change 名称为 `dd-field-by-field-wire-regression`。
- 使用表驱动矩阵和可复用 request-capture harness；生产 builder 如不便隔离，可抽取纯 projection/helper，但不改变 CLI JSON 合同。
- 覆盖维度为 `resource × action × field × applicable state`，不要求对每个字段机械运行不适用状态；每个省略状态必须在报告中给出“保留/默认/清空/拒绝/不适用”的明确结论。
- delete 没有业务字段矩阵，但 identifier、confirm、ownership、endpoint body、mutation count、readback 和错误分类全部纳入。
- 逐字段全量回归以 deterministic capture 为主，代表性 live smoke 为辅；探索赛季继续排除 live 写入。
- `analyze/` 保存详尽矩阵与探索证据且不跟踪；Comet verification 只保存可公开的摘要和项目内测试证据。
- 用户已于 2026-08-01 确认上述完整 Shape 合同并要求直接进入实施。

# Open questions

None.

# Verification expectations

- 运行 `python -m unittest discover -s fupload\scripts\tests -v`，逐字段矩阵测试必须显示稳定 case ID 或生成完整机器可读结果。
- 运行专用矩阵清单检查，证明 schema action fields 与 wire matrix 双向无缺口，并输出每个 resource/action 的字段数、case 数和缺口数。
- 运行 `python -m compileall -q fupload\scripts`。
- 运行 `git diff --check`。
- 运行 `comet native check dd-field-by-field-wire-regression`。
- 对所有非探索赛季 build 运行只读动态依赖 smoke；在安全隔离对象上运行 plugin/config/WA create/update/edit/delete 代表性 live smoke，记录单 session、单 sidecar、mutation 数和 cleanup。
- 运行受控 422/HTTPError fixture，验证 request/response 日志和脱敏；运行 timeout fixture，验证 mutation 不重传。
- 生成并检查 `analyze/dd-field-by-field-wire-regression-20260801.md`，确认每个字段/action/state 映射到测试 ID 和结果，缺口为零。
- 敏感扫描覆盖 tracked diff、Comet 产物和公开测试 fixture；真实凭据、signed URL、clientNo、session ID、账号侧显示信息命中数为零。
- Verify 报告记录实际命令、字面结果、跳过项、规格一致性、已知限制和结论；未运行项不得写为通过。
