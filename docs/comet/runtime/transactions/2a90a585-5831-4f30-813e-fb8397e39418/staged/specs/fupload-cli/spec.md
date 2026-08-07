# Fupload CLI 网页对齐契约

NewBeeBox 第三方 Python CLI 的每个 plugin/config/wa create/update/edit/delete leaf 必须以网页字段矩阵生成完整、阶段受限的 JSON schema、`--help` 和 builder。每个字段都标记路径、JSON 类型、阶段、条件、默认/清空语义、动态来源和读回投影；未知字段、重复键、非标准数字、跨父选择和网页锁定字段在网络请求前拒绝。

写命令先读取当前 detail 与网页依赖选项，在写前重新验证；每步成功后以网页 detail/list/version 读回。输出保持稳定 JSON，并按 `dependency_get`、`upload_authorize`、`object_put`、`mutation`、`readback` 等实际阶段报告脱敏错误。认证和请求 origin 固定为受信官方 HTTPS 地址。
