# Fupload Skill 完整目标规格

## 激活和平台选择

Skill 显示名为 `Fupload`，安装名为 `fupload`，只允许用户显式调用。普通对话提到插件、NewBee 或 DD 时不得自动进入。用户未给出平台/资源/动作时，只问缺失的最上游选择；已经说明时直接调查，不重复菜单。

NewBee 环境检测到官方 `ncc` 时默认使用官方 CLI；未安装时询问是否安装并说明如何取得官方登录态。只有用户显式要求第三方 Python 管理工具时才调用本 Skill 内的 NewBee provider。DD 始终使用本 Skill 的 Python CLI 和已验证官方 native adapter。

自然语言动作映射：create 创建主对象，update 发布插件版本/配置备份内容/WA 内容版本，edit 按各资源官方 allowlist 修改设置，delete 删除一个明确目标。Skill 与 references 必须暴露全部四种动作，不能隐藏 delete。插件 edit 仅展示商业、关联、房间/频道和创建声明控件；首版元数据、分类、媒体和版本字段必须提示为 create/update 专属。

## DD GUI 同意和任务 session

选择 DD 后，先调用不登录的 `dd session doctor`。若发现官方 GUI，Skill 用人话说明将关闭的安装版本和进程数量，并取得一次明确同意。未同意时不调用 start，不关闭进程，不启动 sidecar，不登录。

同意后调用 `dd session start --confirm-close-gui`，保存返回的 opaque session ID 作为本次任务执行上下文。该 ID 不写入发布 JSON、不向用户展示为凭据。本次任务的所有 GET、上传、写入和读回都使用同一 session 且串行执行。无论成功、失败或取消，Skill 在 `finally` 调用 `session stop`；用户需要继续一项新的独立发布任务时重新取得 GUI 关闭同意。

CLI 自动发现并验证 DD 安装目录；只有全部候选失败时才询问路径。不得要求用户提供 token、Cookie、clientNo、`cred.db` 或 GUI 进程内信息。

## GET 驱动的字段选择

Skill 不先写一份带猜测值的 JSON。对于 DD，必须把官方 GUI 的联动顺序显式执行出来：

1. 读取目标详情和顶层 options。
2. 向用户展示父候选的名称、稳定 ID 和关键差异，取得选择。
3. 使用父 ID 调用下一层 GET，展示该父项下的子候选。
4. 重复直到所有条件字段闭合。
5. 最后一次性生成完整业务 JSON，保存到发布目录并展示写入计划。

依赖链包括 `game_type -> game_versions`、主分类 -> 二级分类、scope -> 有效期/会员/同步、outer 免费/付费 -> 付费方式 -> 价格/有效期/VIP、房间 -> 频道、game type -> 关联内容、主播会员开关 -> VIP 等级、`backup_sn -> backup detail -> WTF account/server/role -> account-scoped WA`、retail backup -> UI config selector、game type -> WA 分类，以及 WA 材质开关 -> 文件/安装路径。

对配置，先展示云备份并选择 `backup_sn`，再展示该备份内的插件、WTF、素材、字体和正式服 selector；只有选定 WTF account 后才展示这个账号可用的 known/unknown WA。用户更换备份或 WTF 账号时，Skill 明确清空并重新询问所有下游项，不沿用同名角色或 WA。

最终 JSON 只保存父字段和 CLI 返回的稳定 ID/opaque selector。显示名称写入人类可读计划即可；不复制 GET 的 raw object，不让用户手抄 `import_string`、unknown WA 内部 ID、channel object 或其他 wire 细节。Python 的写前 live GET 复验是强制防线，Skill 的 GET 不能替代它。

## 字段补齐和阶段锁

Skill 按动作加载对应 reference 和精确叶子 help。每个字段在 reference 中标明平台名、JSON path、类型、必填条件、create/update/edit/delete 阶段、清空语义、动态来源、父字段和读回字段。

可从项目文件、远端详情或 options 查明的事实由 Agent 调查；只询问用户的产品选择。网页预选值不构成用户决定。create-only/已有 SN 后锁定字段显示为当前值并说明保持，不能把它放进 update/edit JSON。官方“使用方式”的外层免费/付费为锁定展示态；已有付费对象的付费方式、价格、有效期和会员等级若官方仍开放则继续展示为可编辑子项。父项可编辑时，改变父项必须触发下游重查。

## 发布计划和确认

写入前在被发布项目根创建 `publish/<YYYYMMDD-HHmmss>-<platform>-<resource>-<action>/`；重名追加 `-2`、`-3`。一次计划的 JSON 按执行顺序保存为 `01-<action>.json` 等；同一计划重试和读回继续使用该目录，独立计划创建新目录。不得在 Skill 内或 Skill 外侧创建 release JSON。

Agent 完成所有 GET 后生成一次最终 JSON，并用人话展示：平台、资源、目标 ID、session 已建立状态、原子步骤、全部改变/保留/清空字段、父子选择、文件、版本、备份、商业设置、公开/审核影响和 delete 后果。取得一次计划确认后串行执行，不重复询问同一计划。

## 执行、读回和恢复

每个 mutation 后立即 get/list/history 读回。任一步失败即停止后续步骤，报告已完成动作、远端 ID、确定失败阶段和最小恢复入口。`verification_required=true` 时只做只读核对，不自动重发。平台接受提交不能描述为审核通过。

delete 需要在计划中明确展示资源名称、ID 和不可逆结果，并把 `confirm_delete=true` 写入 JSON。只删除该计划明确列出的对象；读回不确定时不扩大目标或盲目重发。

NewBee/DD 配置都必须从客户端已经上传的云备份选择；空列表时提示用户先在官方客户端上传。Skill 不从本地 WTF 猜备份内容。

## 文档和完整性

Skill references 全量覆盖双平台插件、配置、WA 的 create/update/edit/delete、字段矩阵、GET 依赖、阶段锁、条件清空、上传协议、审核状态、错误恢复和读回。引用按动作渐进加载，但任何字段均可在分发包内找到，不依赖 `analyze/` 或作者机器绝对路径。

DD reference 明确 session doctor/start/status/stop、GUI 同意、单 session、依赖图和 write-time revalidation。NewBee reference 明确官方 CLI 优先规则与第三方 provider 的显式选择。

交付前以真实 help/schema 对 Skill 和 references 做追踪审计，并模拟空候选、父项切换、跨父 ID、无备份、上传 403、对象 PUT 超时、mutation 不确定、readback 延迟、delete 不确定及全部支持 build。探索赛季不做 DD 真实写入。
