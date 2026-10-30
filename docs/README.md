# 当前文档入口

面向使用者和 Agent 的字段契约统一在[平台字段总表](../fupload/references/platform-fields.md)。它包含全部已注册动作的字段、类型、必填/null/边界、接口映射、条件及来源，并区分工具未实现与平台不支持。

操作说明保留在 `fupload/references/` 各平台短指南，不再各自复制完整字段列表。官方 `ncc` 的运行时文档单独保留，因为它不是 Python JSON 接口。

维护总表：

```powershell
npm run build:fields
npm run check:fields
```

`platform-audit/*.json` 是逐字段协议核对输入；同目录说明记录官方代码版本、实际验证范围和未确认项。生成器从真实 Schema 和命令树补齐类型与参数，CI 拒绝遗漏或过期的表格。

调查证据：

- [DD 会话共存](dd-session-coexistence.md)
- [黑盒桌面、短信和微信会话调查](blackbox-desktop-session.md)
- [云备份能力与验证范围](cloud-backup-support.md)

`docs/comet/archive/` 是历史开发快照，不是当前字段或登录方式的使用说明。保留历史验证记录，不再用旧快照覆盖当前总表。
