# Fupload Python 执行层完整目标规格

## 目标与交付

Fupload 的唯一可分发产物是仓库根目录 `fupload/` Codex Skill。原子 CLI 是
`fupload/scripts/` 内可审计的纯 Python 项目，不再包含 Go 源码或编译二进制。Skill 通过
当前可用 Python 解释器调用入口；DD provider 再以 DD 版本匹配的 `netease_dd.exe`
启动原生 adapter。

CLI 使用 `newbee` 和 `dd` 一级平台，三类资源统一提供：

- `plugin create|update|edit`
- `config create|update|edit`
- `wa create|update|edit`

`create` 新建主对象，`update` 只更新版本/备份内容/字符串内容，`edit` 只更新资料、
商业设置、关联和公开状态。底层平台没有独立 update/edit endpoint 时，provider 仍分别
构建动作白名单并用真实 modify endpoint 提交。

只读和附属命令至少覆盖 list/get、动态选项、版本/日志、上传、WA 共创/引用/分享码，
以便 Agent 不依赖硬编码 ID 或网页操作完成上述工作流。不提供任何 delete 命令。

测试后环境清理不改变这一公开命令面：delete 只能存在于被忽略的 `analyze/` 验证工具中，
不能从 `fupload/` 导入为隐藏公共入口，也不能出现在 help、schema 或 Skill references。

## 输入模型

所有写命令只接受 `--input <path|->` 的版本化 JSON 文档；`-` 从 stdin 读取一个 JSON。
每个 schema 拒绝未知字段，并为每个字段标明：

- required：该动作始终必须提供；
- optional：可以省略；
- conditional：只有相关开关/类型/平台状态满足时必须提供；
- create-only、update-only、edit-only：只能在指定动作出现；
- read-only：任何写输入均拒绝。

解析必须保留“字段不存在”和“字段存在且值为空/false/0/[]/null”的差异。edit/update
输入省略字段表示保留远端值；显式空值只在字段允许清空时清空。create-only 或平台 UI
在后续阶段锁定的字段出现在 edit/update 时，必须在发网络请求前报字段路径错误。

CLI 不为需要详情或动态选项的业务字段填猜测默认值。稳定分页、超时、输出格式等技术值，
以及平台公开契约明确规定的常量可以有代码默认；这些默认必须在 help 中说明。

网页表单中所有可选业务字段都必须出现在对应动作 schema、字段表和 help 中，包括分类、
游戏分支/版本、公开状态、付费方式、有效期、频道、关联、备份内容、WA 材质安装方式与路径。
前端预选值不构成 CLI 默认值。create 缺少平台要求选择的字段时本地拒绝；edit/update 省略
字段只表示保留，不能因此从契约中删除该字段。

## Read-modify-write

每个局部 edit/update 按以下顺序执行：

1. GET 目标详情并确认当前状态；
2. GET 该动作依赖的动态选项、备份、分类、版本、频道、会员或关联候选；
3. 将详情转换为资源专用内部 form model；
4. 按字段存在性应用输入，执行条件清空与阶段锁定检查；
5. 用资源专用 allowlist builder 重建完整 wire payload；
6. 执行上传和最终写请求；
7. GET 详情、列表或版本历史读回关键字段。

读取失败、候选已失效或当前状态与计划冲突时停止。禁止把详情 map 直接 update 后 POST；
作者、审核、下载统计、临时 URL、哈希、原始备份和其他只读字段不得进入 payload。

## 输出、help 与错误

所有命令支持稳定 JSON 输出，顶层包含 schema、platform、operation、success、data/error。
每一级命令和叶子命令都有详尽 help；写命令 help 包含动作边界、字段表、条件规则、阶段
限制、JSON 示例、审核影响和失败恢复。Skill 机器调用总是使用 JSON 输出。

写命令支持 `--dry-run`。dry-run 执行 schema、本地文件和无需远端的规则检查，不上传、
不写远端，也不声称远端权限或动态 ID 有效。实际写前确认由 Skill 负责，CLI 不交互。

错误只包含平台、endpoint 名称、HTTP/业务码和脱敏信息。token、Cookie、JWT、登录 code、
signed URL、DD clientNo、原始 WA 字符串和敏感备份内容不得输出。网络结果不确定时返回
`verification_required`，调用方必须先运行只读核对，不能自动重发。

## 上传与幂等

媒体、插件包和 WA 材质上传按平台真实 MIME、大小、扩展名与超时校验。插件版本上传前
查询远端版本并计算本地 SHA-256；相同版本已存在时默认拒绝覆盖。主对象创建成功但后续
版本、媒体或附属动作失败时返回已创建 ID 和可重试的原子步骤，不重复创建主对象。

从私有切到公开必须显式输入审核意图，并在结果中区分“提交审核”“审核中”“审核通过”与
“审核拒绝”。新建默认私有；update 不隐式改变公开状态。

## 仓库边界

除 `.gitignore`、工作流配置/规格外，产品代码和文档只位于 `fupload/`。拆包内容、探针、
调查报告和中间结果位于被忽略的 `analyze/`。Git 不跟踪 Go 文件、EXE、ZIP release、
客户端拆包、运行缓存、设备状态或凭据。

## 全量验证与审计

验证从平台动态接口枚举 NewBee 与 DD 当时全部游戏 build，不硬编码截图中的数量、名称或 ID。
每个 build 的版本、分类、列表、备份和资源引用必须独立验证，跨 build 值不得静默接受。CLI
help 暴露的每个叶子接口都必须在验证矩阵中有真实通过、预期拒绝或明确受限理由；主资源写入
均立即读回，网络结果不确定时只读核对后再决定是否重试。

单元和合同测试覆盖全部 schema 字段、阶段拒绝、显式空值、条件两侧、嵌套对象、分页、错误
脱敏、最终一致性和 adapter 失败。真实验证后复审 Python provider、schema/help、Skill references
与规格追踪关系；任何 finding 修复后重跑最小相关测试和全量回归，最终不得遗留未解释问题。
