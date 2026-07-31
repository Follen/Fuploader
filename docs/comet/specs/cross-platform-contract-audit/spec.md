# 双平台契约审计与写入读回

## 目标

插件、配置和 WA 的每个写动作都使用平台真实的字段语义，并且成功结果必须由对应读接口证明。

## 要求

- NewBee 插件版本的 `game_version_list` 是实时 metadata 返回的 build 字符串数组，例如 `"3.80.2"`；父分支对象的整数 `id` 不得作为上传值。
- NewBee 插件上传前展开实时 build 列表校验，上传后在版本列表中定位新版本并要求存在至少一个 `versions` 绑定。
- NewBee 的 `content_origin`、`subscribe_plan_level`、`time_range` 必须分别从当前来源列表、订阅等级和付费时长接口取得；插件/WA 分类及 WA 附件安装选项也必须使用端点专用解析器，选项空响应时停止写入。
- NewBee 插件 create 固定创建私有记录并关闭频道关联；只有首个版本存在后，才允许通过 edit 应用用户明确要求的公开审核状态。
- NewBee 插件分类最多 5 个、WA 分类最多 5 个；配置和 WA 的一次性付费时长只能使用实时值并只在相应付费模式下发送。
- DD 插件、配置和 WA 继续通过 sidecar 获取当前 game type/build、分类、频道、关联和商业枚举；选项空响应、失效值或条件字段不完整时停止写入。
- DD 插件主分类只能选顶层项，次分类只能选其直接子项；关联内容按 `(act_type, sn)` 校验。频道允许仅房间关联，或完整的房间/频道/频道类型三元组，禁止半个频道元组。
- DD `creation_statement` 只接受 `original/chinesize/renovate/second`，`addon_type` 只接受 `0/1`，`release_type` 只接受 `1/2/3`；配置价格为 0 或 10..20000 分。
- DD 图片最多 8 张、WA 分类最多 5 个；WA 文件安装路径只接受 `Interface/Addons`、`Interface` 或游戏根目录的官方 wire 表示。
- DD 插件 create 的 `html_desc`、`update_desc` 非空；动态响应使用端点专用解析，禁止递归收集任意 `value` 字段。
- create/update/edit 使用动作白名单和完整 GET 回填，省略字段保留当前值，显式空值按平台契约清除。
- DD 非 create 写入前必须比较详情与作者列表中同一 SN 的更新时间；详情落后时允许一次只读复查，仍未收敛则在 POST 前返回 `verification_required`，不得用陈旧详情构造全量 modify。
- DD 配置 metadata edit 的读回必须同时证明 `update_desc`、七个内容组、各组 `inner_version` 和 retail UI 状态没有因省略而回退；平台新增的只读字段可以存在，但期望字段和值必须完整匹配。
- 每次写入按资源逐字段比较对应详情、列表或版本读回，不能仅依据 HTTP/业务提交成功判定完成；审核导致新版本暂不可见时必须返回 `verification_required`。

## 验收

- Schema 接受 NewBee build 字符串并拒绝整数父分支 ID。
- 双平台现有测试通过，新增回归覆盖错误类型、动态值校验、分类父子关系、频道 room-only、关联类型、数量/价格/枚举边界、未绑定读回和逐字段读回失败。
- 真实 NewBee metadata/版本读接口可运行；DD sidecar 失败时输出可诊断的实际原因。
