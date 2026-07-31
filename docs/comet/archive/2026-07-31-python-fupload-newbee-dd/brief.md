# Outcome

把 Fupload 重构为一个可直接分发、显式调用的纯 Python Codex Skill。Skill 同时支持
新手盒子（`newbee`）和网易 DD（`dd`）的插件、配置分享、WA/字符串创建、内容更新和
资料编辑；每个平台覆盖生产表单的全部可写字段、动态选项、阶段限制和写后读回。

# Scope

- 最终可分发物只有根目录 `fupload/` Skill：`SKILL.md`、`agents/`、`references/`、
  `examples/`、`scripts/`。Python CLI 与 provider 全部位于 `fupload/scripts/`。
- 删除 Go/Cobra 源码、Go 构建文件、旧二进制和旧 `Release/` 包；CLI 改为标准库优先
  的 Python 项目，由 Skill 通过 Python 解释器显式调用。
- 保留一级平台 `newbee`、`dd`，为插件、配置和 WA 提供 `create`、`update`、`edit`
  以及完成工作流所需的 list/get/options/history/media/relation 等只读或原子命令。
- `create` 创建主对象；`update` 更新插件版本、配置备份内容或 WA 字符串版本；
  `edit` 修改元数据、图片、商业设置、关联和公开/审核状态。平台底层接口名称可以不同。
- NewBee 覆盖插件、配置、WA 的全部已确认字段、版本日志、WA 附件、共创、关联内容和
  分享码。配置引用客户端已经存在的云备份，不替代客户端的本地扫描上传。
- DD 使用生产客户端随附的 `netease_dd.exe`、原生模块、`AccountCredStorage`、
  `MobileReLoginFlow`、`JwtHelper`、`UiApiClient` 和 `NepWrapper`，实现三类资源完整字段
  builder、上传、create/modify 和读回。
- DD 安装目录由程序自动发现并校验；稳定独立 `clientNo` 保存在当前用户的 DD 数据
  目录 `%APPDATA%/CCVoiceHub/Fupload/sidecar-device.json`，不进入仓库或 Skill。
- 拆包中间体、探针、旧探索代码和探索报告统一放在根目录 `analyze/`，整个目录不跟踪。
  面向 Agent 的正式字段契约保留在 `fupload/references/`。
- Fupload Skill 只允许用户显式调用；用户未显式调用时不得自动进入发布流程。

# Non-goals

- 不实现公开删除命令、草稿、攻略、频道消息发送或 Computer Use 自动化。平台 delete 仅在
  `analyze/` 的本次验证清理中使用，不属于可分发 Skill/CLI。
- 不复刻 DD 的凭据加密、NEP 签名算法或 GUI；不复制、修改、输出 `cred.db`。
- 不把 NewBee/DD token、Cookie、JWT、signed URL、原始角色备份或本机设备 ID 写入
  manifest、日志、Git 或普通输出。
- 不承诺 DD provider 在没有 Windows DD 官方客户端及版本匹配原生模块的平台运行。
- 不保留 Go CLI 或旧二进制兼容入口；Skill 是主要接口，Python CLI 是原子执行层。

# Acceptance examples

- 用户显式调用 Fupload 并要求“给 NewBee 插件发新版”时，Agent 查询插件和动态游戏
   版本，整理 ZIP、版本号和日志，一次确认后调用 `newbee plugin update`，随后从版本列表
   读回；它不修改插件名称、分类或公开状态。
- 用户只给 NewBee 插件 ID 和新简介执行 `edit` 时，Python 先 GET 详情，保留未提供的
   分类、正文、媒体和商业字段，只替换简介；若显式提交公开则先核对已有版本并展示审核影响。
- 用户以 NewBee 客户端云备份更新配置时，程序先 GET 当前配置和备份安全详情；若更换
   `cloud_id`，必须显式提供或由 Agent确认新的插件关联、忽略项和角色选择，不能沿用旧备份猜值。
- 用户创建或更新 NewBee WA 时，所有元数据、字符串模式、附件、版本日志、共创、引用、
   分享码和公开状态均可表达；主对象或版本成功而附属步骤失败时保留 ID 并给出可重试步骤。
- 用户选择 DD 时，程序自动定位安装版本并用官方无头客户端启动单例 sidecar；首次创建
   稳定 `clientNo` 到 DD 用户目录，以后复用。目录损坏、客户端版本不匹配或并发实例均在
   发请求前失败，且错误不包含凭据。
- DD 插件 `edit`、配置 `update` 或 WA `edit` 收到局部输入时，程序先读取详情、选项及
   必要关联数据，构建平台要求的完整 payload。省略字段保持远端值，显式空数组清空允许清空
   的集合；create-only/锁定字段出现在不允许的阶段时本地拒绝。
- DD 配置更新先读取 `/share/detail`、`/backup/list` 和 `/backup/detail`，重建七组内容、
   WTF 树、`inner_version` 与正式服 `retail_ui_config`；不能把详情字典直接 POST。
- `fupload/` 目录复制到朋友的 Skill 目录后，可阅读全部 Python 源码并显式调用；仓库的
  `analyze/`、Go 文件、EXE 和本机状态均不在分发目录中。
- Build 完成后，验证从两个平台的动态接口读取当时全部魔兽世界 build；逐个 build 验证
  版本、分类、列表和资源动作不会串用 ID、分类或备份。所有 CLI 暴露的只读、上传、主资源
  和附属接口均有真实或明确受限的验证结论，不能只以单元测试代替生产链路。

# Constraints and invariants

- 页面中所有可选业务字段都必须暴露给用户或 Agent；前端预选值不构成 CLI 默认值。创建时平台要求选择的字段缺失即本地拒绝，编辑或更新时省略字段仅表示保留远端值。
- 所有写命令采用版本化 JSON 输入、严格未知字段检查、稳定 JSON 输出和非零错误码。
- 字段必须区分 required、optional、conditional、create-only、update-only、edit-only、
  read-only；不得用真假值默认判断字段是否存在。
- 只在协议明确允许时采用常量默认值；依赖远端详情或动态选项的值必须 GET，读取失败即停止。
- 所有 edit/modify 是 allowlist read-modify-write，不允许 `detail.update(input)` 或通用 map
  透传；GET 响应中的作者、审核、统计、临时 URL 和内部状态不得进入写 payload。
- 新建默认私有；私有转公开是显式提交审核，必须在 Skill 计划中展示并由用户确认。
- 上传有大小、扩展名、MIME、超时和重复版本保护；不确定结果先只读核对，不盲目重试。
- DD sidecar 同一 Windows 用户只允许一个实例；GUI DD 与一个独立设备 sidecar 可并存。
- NewBee 复用桌面客户端认证状态；DD 复用官方客户端本机凭据和签名能力；两者都不索要 token。
- `analyze/`、缓存、客户端拆包、设备状态和 Comet runtime 不进入 Git。

# Decisions

- 2026-07-31：采用纯 Python 全量替换，不保留 Go 兼容层。
- 2026-07-31：最终分发结构为单一 `fupload/` Skill，Python 工程使用标准 `scripts/` 目录。
- 2026-07-31：统一用户语义为 create/update/edit，底层仍忠实使用各平台真实接口。
- 2026-07-31：局部修改由 Python 自动 GET 并完整重建；省略保留，显式空值按字段规则清空，
  不允许想当然默认。
- 2026-07-31：DD 采用已验证的稳定独立设备 sidecar 方案，设备状态归属 DD 用户目录。
- 2026-07-31：Skill 必须显式调用，所有平台字段与工作流写入 Skill references。
- 2026-07-31：探索材料移入不跟踪的 `analyze/`，正式产品契约与测试继续跟踪。
- 2026-07-31：原决定为不提供删除能力；用户随后要求全量测试完成后调用平台 delete 接口清理
  本次创建的全部测试内容，因此该决定已重新进入澄清。
- 2026-07-31：所有页面可选业务字段均交给用户选择，不以网页预选或代码默认静默代选。
- 2026-07-31：用户确认完整共享理解，批准进入 Build。
- 2026-07-31：用户重新确认当前完整合同，并要求完成后对 NewBee 与 DD 的插件、配置、WA
  分别执行真实 create、update、edit，总计十八条写工作流；每条都必须写后读回并记录对象。
- 2026-07-31：发布合同中的“频道”指内容表单的频道关联/同步字段，不包含频道历史抓取或
  消息发送；凡平台在插件、配置或 WA 表单提供该字段，均属于全字段覆盖范围。
- 2026-07-31：Build 完成后，对 NewBee 与 DD 当前动态返回的全部魔兽世界 build 和 CLI
  暴露的全部接口做真实验证；发现问题即修复并回归，再审计代码、规格测试、Skill 完整性和
  边缘情况，重复修复与复审直到没有已知问题。
- 2026-07-31：验证通过后完成 Comet Archive，随后合并当前分支到 `main`，确认合并结果后
  删除 `python-fupload-newbee-dd` worktree。
- 2026-07-31：用户要求全量测试完成后调用 NewBee/DD 的 delete 接口，删除本 change 创建的
  全部测试对象；不得删除测试前已经存在的用户内容。
- 2026-07-31：用户确认 delete 只用于测试后保持当前环境干净，不是 Fupload 正式功能；公开
  Skill/CLI 继续不提供 delete，清理脚本不进入分发目录。
- 2026-07-31：用户确认包含测试后私有清理流程的最终合同，批准恢复 Build 和完整收尾。
- 2026-07-31：用户确认当前 NewBee 与 DD 的云备份已覆盖两平台全部可见 build，唯一例外是
  NewBee 的“探索赛季”；验证时重新动态读取列表确认，不依赖聊天中的静态 ID。
- 2026-07-31：NewBee“探索赛季”不执行配置 create/update/edit；该 build 仍执行动态只读、
  插件和 WA 验证，并确认配置工作流在无云备份时正确停止。NewBee 其余五个 build 与 DD
  全部五个 build 执行配置真实写验证。
- 2026-07-31：用户确认更新后的完整合同，批准继续 Build、全接口全 build 验证、审计修复、
  Verify/Archive、合并 `main` 和删除 worktree 的完整收尾流程。

# Open questions

- 无。

# Verification expectations

- 对每个平台、资源、动作建立字段矩阵测试：每个字段至少覆盖接受、拒绝阶段、显式清空和
  省略保留中的适用情形；条件字段覆盖开关两侧。
- 使用 mock HTTP/native adapter 合同测试验证端点、字段名、嵌套转换、GET 顺序、上传 MIME、
  重复版本保护、错误脱敏和写后读回。
- NewBee 执行已登录环境只读 smoke test，并对授权测试对象执行受控 create/update/edit 回归。
- DD 用当前安装客户端运行 session doctor、安装发现、稳定 clientNo、单例和三类资源 GET；
  使用明确标识的隔离测试对象，对插件、配置、WA 分别执行真实 create、update、edit，逐次
  写后读回；不修改既有正式对象，不调用 delete，并在报告中列出所有保留测试对象及状态。
- NewBee 使用明确标识的隔离测试对象，对插件、配置、WA 分别执行真实 create、update、edit，
  逐次写后读回；不修改既有正式对象，不调用 delete，并在报告中列出所有保留测试对象及状态。
- 验证 Skill 只有显式调用路径，模拟自然语言工作流，校验一次确认、失败停止和剩余对象报告。
- 验证干净复制的 `fupload/` 可运行全部 help/schema 测试，且 Git 中不存在 Go、EXE、探索报告、
  拆包中间体、凭据或设备标识。
- 枚举 NewBee 与 DD 当前动态返回的全部游戏 build；每个 build 至少覆盖版本、插件分类、WA
  分类、作者列表及输入校验，验证 build-specific ID 不串用。插件和 WA 的 create/update/edit
  执行真实写入；配置在 NewBee 探索赛季验证无备份停止，其余 NewBee/DD build 均执行真实
  create/update/edit 并读回。
- 枚举 CLI help 暴露的全部叶子接口，逐项记录真实通过、预期拒绝或明确跳过理由；上传、共创、
  引用、分享码、频道关联、商业条件、备份选择和 DD 原生 adapter 边界均纳入。
- 完成实现后执行代码审计、规格回归覆盖审计、Skill/references 完整性审计和边缘情况审计；
  每轮 findings 修复后重跑受影响测试并复审，最终报告不得遗留未解释的已知问题。
- 全量真实验证结束后，仅根据验证报告中本次创建并读回确认的对象 ID/SN 调用平台 delete，
  再次 list/get 确认对象已删除；任何归属不确定、删除结果不确定或测试前存在的对象都不得删除。
