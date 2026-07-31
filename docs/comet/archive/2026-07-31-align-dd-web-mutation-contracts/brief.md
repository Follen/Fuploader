# Outcome

重新审计并修复 DD Python provider，使插件、配置与 WA 的 create、update、edit、delete 以及全部依赖 GET、上传、mutation、读回和错误诊断链路逐项对齐当前安装版 DD 官方网页与官方原生客户端。不得再以 mock 通过、endpoint 返回成功或单个实测对象作为“全量对齐”结论；最终结论必须由可复核的字段矩阵、源码证据、合同测试、全量测试和受控真实验证共同支持。

# Scope

- 以 `analyze/dd-official-web/umi.pretty.js`、当前安装 DD 的官方 Python bytecode/disassembly、实际 endpoint 行为和官方表单读回投影为权威证据，重新提取插件、配置、WA 的完整页面初值、打开编辑器投影、父子联动、校验、最终 builder、上传 descriptor、mutation payload 与读回链路。
- 覆盖插件、配置、WA 的 create、update、edit、delete；覆盖所有公共商业字段、频道/房间、关联内容、分类、游戏版本、备份/WTF/WA/素材/字体/正式服 UI 配置、WA 解析和附件字段。
- 对每个 wire 字段记录：字段名、类型、来源、动作、缺失/null/空值语义、新建默认值、存量保留规则、条件清空规则、父依赖、上传前校验、最终 endpoint 和读回投影。
- 审计并修复 Python schema、builder、动态选项、sidecar、上传、错误分类、读回、CLI help/examples、Skill 与 DD reference；删除与官方链路矛盾的历史兼容逻辑和未经证实的 fallback。
- 对 HTTP/业务拒绝，在 DD 安装版本目录 `Fupload/logs` 中保存脱敏后的实际请求 JSON/body、响应 JSON/body、HTTP 状态、原生业务码、endpoint、stage 和字段校验提示。错误请求体必须在官方客户端读取或丢弃前被捕获；CLI 输出只返回安全摘要和日志路径。
- 在 `analyze/` 输出本轮完整审计报告，列出官方证据位置、逐操作请求矩阵、发现的每一项差异、修复、测试覆盖、真实验证结果、剩余限制和结论。报告不得只列成功摘要。
- 更新正式 `dd-publishing` 规格，使归档后长期契约反映本轮证实的行为。

# Non-goals

- 不修改 NewBeeBox provider 的业务行为。
- 不支持探索赛季真实写验证。
- 不修改或删除用户已有正式对象；真实写只使用本轮明确标识的隔离测试对象，并在确认写入状态后清理。
- 不以重复提交 mutation 的方式探测结果；不确定写入先只读核对。
- 不把 Token、Cookie、JWT、clientNo、签名、签名 URL 凭据或认证目录内容写入日志、报告或 CLI 输出。

# Acceptance examples

- 存量插件缺少 `buy_life_type` 时，plugin update 的 `/addon/modify` 请求不得注入新建默认值；字段缺失、显式 null、零值和空数组必须与官方 `open -> form state -> submit` 路径一致。
- 插件详情包含 `latest_version` 和尾部汇总分类时，Python 按官方修改弹窗的真实打开顺序生成 game/version/file/category 字段：稳定字段和顶层 build 来自 detail，同一 SN 作者列表项只补 detail 中为 null/缺失的 latest-version 字段；更新后的版本通过官方实际读回投影确认。
- 配置切换 backup 或 WTF 账号时，所有依赖组和 selector 失效并从 live backup 重建；edit/update 不会因陈旧详情回退 inner version 或正式服 UI 设置。
- WA create 默认值只作用于 create；update/edit 保留存量字段并每次调用官方 WA2 解析链，材质有无与安装路径按官方 builder 提交。
- `/addon/modify`、`/share/modify` 或 `/wa/modify` 返回 4xx 时，同一次调用的本地错误日志包含脱敏后的实际请求 body 和官方读取到的响应 body；HTTPError body 被读取后官方客户端仍收到完全相同的 bytes。
- 特殊 ZIP 文件名包含空格、中文、括号、`+`、`#`、`%` 时，上传授权参数仍使用官方固定/空/省略的 wire `file_name`，业务 payload 只使用授权返回的 `d_url`。
- 静态矩阵中的每个 mutation 字段都有至少一个合同测试；每个条件字段都有开启、关闭、缺失/保留或无效组合测试；测试能在旧实现上暴露至少一项本轮确认的错配。
- 当前 DD 环境的非探索赛季 build 完成动态只读矩阵；具备依赖和权限的隔离对象完成 plugin/config/WA create、update、edit、delete 与读回，整个任务只建立一次 DD 原生登录并在结束时退出。

# Constraints and invariants

- 官方网页最终 builder 和原生客户端 transport 是 wire 契约；详情/list 返回对象不能直接透传，也不能用通用默认归一化替代各资源、各动作的官方行为。
- 新建默认值与存量修改投影必须分离。省略字段只能按官方页面行为保留或省略，不得因 Python truthiness、`dict.get` 或共享 helper 静默改写。
- 所有父子依赖在上传和 mutation 前完成 live GET 与归属校验；任何失败不上传、不 mutation。
- 错误日志保存在 DD 安装版本目录内，使用 JSONL、大小有界、递归脱敏，并记录截断状态。日志不得记录认证 header、签名参数或 clientNo。
- 真实 DD 操作前运行 session doctor。若 GUI 正在运行，必须取得用户对本次关闭 GUI 的明确同意；一次任务只登录一次，严格串行，finally 中 logout/stop。
- `analyze/` 中间文件和探索报告保持 Git ignore；正式代码、测试、Skill/reference 和 Comet 规格正常跟踪。
- 不自动重试可能已经发送的写请求；显式 4xx/业务拒绝为确定失败，连接不确定或读回不确定按既有阶段契约处理。

# Decisions

- 2026-08-01：用户要求重新完整执行 DD 全量对齐，不能只修一两个已发现字段。
- 2026-08-01：用户要求在 `analyze/` 输出完整报告，并捕获错误调用的实际请求体和响应体。
- 2026-08-01：用户确认 Shape 完成后直接进入 Build，不再等待第二次确认。
- 2026-08-01：此前确认探索赛季不做真实业务验证；真实测试对象仅用于保持环境干净，完成后清理。

# Open questions


# Verification expectations

- 生成官方网页/原生链路到 Python 实现的逐字段、逐操作、逐 endpoint 对照矩阵，并在报告中引用准确文件和行号或 disassembly 符号。
- 为每项发现增加回归测试，重点覆盖缺失/null/false/0/空字符串/空数组、create-only 默认值、父选项变化、旧记录字段缺失、特殊文件名和 HTTPError body 消费。
- 运行 `python -m unittest discover -s fupload\scripts\tests -v`、`python -m compileall -q fupload\scripts`、`git diff --check`，并审计 CLI help/schema/examples 与 Skill/reference 一致性。
- 运行 DD session doctor 和全量动态只读矩阵；真实写验证严格记录命令、输入文件、SN、读回、退出码、登录次数、GUI/sidecar 进程状态和清理结果。
- 最终报告逐项说明已证实、已修复、跳过及原因、残余风险；只有全部验收项有直接证据且没有未解释 finding 时才可通过 Verify。
