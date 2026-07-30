# Outcome

扩展 Fupload，使 Agent 能通过已登录的新手盒子会话完成插件版本日志与 WA（字符串内容）的完整非删除业务链路。CLI 保持原子化，Fupload Skill 负责收集资料、展示执行计划并编排原子命令。

# Scope

- 插件版本日志：版本日志列表、读取单个版本日志、编辑单个版本日志。
- WA：列表、详情、分类、附件安装路径、封面/截图媒体上传、创建、编辑元数据、获取下一版本号、发布新字符串版本、读取最新字符串信息、版本日志列表与编辑。
- WA 相关非删除附属链路：联合作者搜索/列表/设置、关联内容搜索/列表/设置、分享码设置。
- `newbee` 平台的 Cobra CLI、结构化 JSON/YAML 输入、详尽 help、原子命令和 Fupload Skill 路由/资料整理/失败恢复。
- 现有插件、配置能力的命令契约继续保留；新增能力必须遵循现有平台 adapter、会话复用和输出 schema。

# Non-goals

- 不实现网易 DD；仅保留 `dd` 平台扩展点。
- 不实现草稿保存/恢复/发布：不调用 `/creator/content_draft/*`。
- 不提供任何删除命令或删除接口，包括 `/creator/wow/wa/delete` 和 `/creator/wow/wa_log/delete`。
- 不绕过审核；“公开”只表示提交公开/审核状态，不能报告为审核已通过。
- 不扫描或上传本地 WoW 配置；配置仍只引用客户端已上传的云端备份。
- 不实现本地 WA 材质文件上传；本次仅允许把已经取得的远端材质 `value` 写入 `attachments`。
- 不在本次穷举发布页全部设置的枚举与组合校验，也不新增合集条目对象输入；这些能力由后续独立 change 处理。

# Acceptance examples

- `fupload newbee plugin changelog list --mod-id 20745 --output json` 返回版本文件 ID、版本和日志摘要。
- `fupload newbee plugin changelog get --file-id 557441 --output json` 返回当前日志；`edit --input` 只修改该版本日志，不上传新版本。
- `fupload newbee wa list`、`wa get`、`wa categories` 和 `wa attachment-paths` 可读取当前作者可见数据。
- `wa create --input` 能上传明确提供的封面/截图媒体并创建 WA；附件使用已有远端材质 `value`；集合字符串按 `wa_str` JSON 数组文本与并行 `wa_str_titles` 发送。
- `wa edit --input` 只修改已有 WA 元数据；`wa publish-version --input` 先取得下一版本号，再发布字符串和版本日志。
- `wa changelog list|get|edit` 能管理 WA 版本日志；编辑不会隐式发布新字符串版本。
- WA 写入成功后，Skill 可按输入编排共创作者、关联内容和分享码设置；任一步失败会停止并报告已完成步骤。
- 所有写命令均支持 `--dry-run`，缺少必填字段或未知字段时不发网络写请求。

# Constraints and invariants

- 认证复用本机 NewBeeBox 已有登录态；凭据、token、原始 WA 字符串和预签名 URL 不进入普通输出。
- 成功条件为 HTTP 2xx 且业务响应 `code == 1`；错误包含脱敏 endpoint、HTTP 状态、业务 code 和 message。
- 区分 API 必传、网页条件必传和可选字段；只有业务条件满足时才发送条件字段。
- 新建未明确公开时保持私有；已有内容更新按既定策略设置公开并如实报告审核状态。
- 版本号冲突不得盲目覆盖；不确定结果先只读核对远端状态。

# Decisions

- 版本日志能力覆盖插件和 WA 两类内容。
- WA 范围按“除删除之外的全部相关接口”解释，包含共创、关联内容和分享码附属链路。
- 草稿明确不在本 change 内。
- 首版平台为 `newbee`，保留未来 `dd` adapter 接口。
- 用户已确认按本 brief 和两份拟议规格进入 Build。
- Build 期间依据线上静态 chunk 与真实分类请求修正 WA 字段契约：分类使用 `game_version`；私有值为 `2`；分类/封面为网页必填；附件、共创和关联内容使用结构化对象数组。
- 用户已确认上述字段级规格修订；当前账号没有 WA，因此本 change 不创建无法清理的测试 WA，线上写入留待用户提供真实 WA 后验证。
- 用户要求先验证并归档本 change；完整发布设置、结构化合集输入和本地材质上传拆到后续较大的 change。

# Open questions

- 无。

# Verification expectations

- 运行 Go 单元测试、CLI 全量 `--help` 检查、输入 schema/校验测试和 dry-run 测试。
- 用脱敏的已登录会话对列表/详情/版本号/日志读取做真实接口验证；写入测试使用用户指定的测试 WA/插件并记录响应，不测试删除和草稿。
- 验证每个 Acceptance example 的命令、输出 schema、失败边界和 Skill 编排停止行为。
