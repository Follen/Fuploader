# 主记录删除命令

## 目标

在 Fupload Skill 与 Python CLI 中提供 NewBeeBox、DD 的插件、配置、WA 主记录删除命令。

## 要求

- 每个平台的 `plugin delete`、`config delete`、`wa delete` 都要求单个明确的目标 ID/SN 和独立确认值；没有确认时只允许 dry-run/拒绝写入。
- 删除前读取目标详情并核对目标类型和归属；目标不存在、归属不满足或详情不一致时停止。
- 调用平台官方删除接口后再次 GET/list 验证目标已删除；结果不确定时返回 verification-required，不自动重试。
- CLI help、Schema、Skill 工作流参考和错误输出明确区分 dry-run、确认缺失、删除成功和读回不确定。
- 删除操作不提供批量删除，不删除版本文件、上传媒体或其他关联对象，除非后续平台事实和用户确认扩展范围。

## 验收

- 两个平台六个命令均出现在 help，并有 schema/provider/CLI 测试。
- 缺少确认、目标不存在和读回不一致的测试均不产生删除请求。
- 成功路径验证目标不存在或已从作者列表移除，并保留脱敏结果。
