# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0333b05c8de70b5b58d437e28885d13193297d61925b8a4c2e871e52ce11718c",
    "evidence_refs": [
      "Release/fupload/references/wa.md",
      "internal/cli/wa_relations.go",
      "internal/newbee/wa.go"
    ]
  },
  {
    "acceptance_id": "acceptance-375e63f5df23e83e17ceb9111e22999dd824dcbe9eeddeb6d4fcaeef29569aef",
    "evidence_refs": [
      "examples/newbee/wa-create.yaml",
      "internal/newbee/service_test.go",
      "internal/newbee/wa.go"
    ]
  },
  {
    "acceptance_id": "acceptance-3d0702329798bd2b99cef58eabf8322d7ee6e321abcb43f7948c3f6b9d0d8e00",
    "evidence_refs": [
      "internal/newbee/changelog.go",
      "newbee.md"
    ]
  },
  {
    "acceptance_id": "acceptance-4af8e60e150ef52949323bf510c5f5c7fb01adaa7b08ad9c3a3810e1a938a026",
    "evidence_refs": [
      "internal/newbee/service_test.go",
      "internal/newbee/wa.go"
    ]
  },
  {
    "acceptance_id": "acceptance-86e983b130c0af0894f3ccf5a1147e090c737c250be256ce02534e678a8780f8",
    "evidence_refs": [
      "internal/cli/wa.go",
      "internal/newbee/service_test.go",
      "internal/newbee/wa.go"
    ]
  },
  {
    "acceptance_id": "acceptance-87bbf15eec2e6d6180db6a936a4c20366dbb999c3bc5e0410eae34de8b4d3999",
    "evidence_refs": [
      "internal/cli/root_test.go",
      "internal/input/input_test.go",
      "newbee.md"
    ]
  },
  {
    "acceptance_id": "acceptance-88d2ac28f7739c56760872fc5d24d10f42bd28730e248e5da7175a82e163b355",
    "evidence_refs": [
      "internal/newbee/wa.go",
      "newbee.md"
    ]
  },
  {
    "acceptance_id": "acceptance-f44f334709d04690db5b5c4979e640828c98d00ba72294d56696e4fb36ad79d8",
    "evidence_refs": [
      "internal/newbee/changelog.go",
      "newbee.md"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `go test -count=1 ./...`：通过；`internal/cli`、`internal/input`、`internal/newbee`、`internal/platform`、`internal/skill` 全部成功。
- `go vet ./...`：通过，无输出。
- 23 个新增叶子命令逐一执行 `--help`：全部退出码为 0，且均包含 `Usage` 与 `Examples`。
- `wa create` 单体示例和两条合集 JSON 文本分别执行 `--dry-run --output json`：均通过，原始 WA 字符串仅输出长度与 SHA-256 摘要。
- 带未知字段的 WA dry-run：在本地以 `json: unknown field` 拒绝；缺少分类/封面的输入在本地拒绝，未发网络写请求。
- `option game-versions --output json`：线上成功，返回正式服、泰坦重铸、熊猫人之谜、燃烧的远征、经典旧世和探索赛季；正式服当前 ID 为 2。
- `wa list --output json`：线上成功，当前账号返回 `total: 0`。
- `wa categories --game-version-id 2 --output json`：线上成功，返回正式服分类，包括原创、汉化、转载、职业和内容分类。
- `wa attachment-paths --output json`：线上成功，返回 AddOns、Interface 和根目录三个安装路径。
- `plugin changelog list --mod-id 20745 --output json`：线上成功，返回 2 条版本记录。
- `plugin changelog edit` 对 `file_id=557441` 执行同值编辑：线上成功；随后 `plugin changelog get` 读回相同日志。
- `bin/fupload.exe` 与 `Release/fupload/bin/fupload.exe` 的 SHA-256 都是 `49F6A1268EC6B7D3836CD8841D20DDE46C93507047FD6D688CF969558B4F53A5`。
- `Release/fupload.zip` 包含 Skill、agent metadata、原生 CLI 及 CLI/config/plugin/WA 四份参考文档。

# Skipped checks

- 当前账号没有 WA，未创建无法删除的测试 WA；因此 WA 创建、元数据编辑、字符串新版本、日志编辑、共创、关联内容和分享码没有执行线上写入。对应请求结构、调用顺序和失败停止行为由 HTTP mock 单元测试覆盖。
- 未测试删除和草稿接口；两者均为明确非目标，CLI 不提供相应命令。
- 本地 WA 材质文件上传、发布页全部设置的枚举/组合校验和合集条目对象输入已按用户要求拆到后续 change。
- `comet native check` receipt `c940140526daaa8bc326fbad76cfbf92bc98c577804dcf4b821e9618e2c8f998` 未作为通过证据：唯一 issue 是 `bin/fupload.exe` 超过内置 1 MiB 文本扫描上限，receipt 显示 0 个文本文件被扫描；源码质量由 Go test、vet 和命令验证覆盖。

# Spec consistency

- 插件日志 list/get/edit 分别映射独立 endpoint；同值线上编辑与读回证明写链路可用。
- WA 查询、分类和附件路径已用真实登录态验证；分类请求使用前端真实字段 `game_version`。
- WA 创建输入使用 `share_state` 的 1/2 语义、至少一个分类与封面、结构化附件对象；单体/合集序列化与元数据编辑/新版本分离由单元测试覆盖。
- CLI 不包含删除或草稿命令；公开只描述为提交公开/可能进入审核，不描述为审核通过。
- implementation scope 使用已确认 partial allowance，仅排除用户明确要求另开 change 的 `dd.md` 与 `DD/auth-analysis.md`。

# Known limitations and risks

- WA 写接口尚缺真实对象验证；未来拿到用户已有 WA 后，应优先做同值元数据编辑和版本日志读回，避免创建残留对象。
- 当前合集输入仍是 `wa_str` JSON 数组文本加同序 `wa_str_titles`，未提供结构化条目数组与数量一致性校验。
- `attachments.value` 必须由调用方提供已有远端材质引用，CLI 尚不能上传本地材质文件。
- 发布设置字段已能透传，但完整枚举、人类可读选项和组合校验属于后续大 change。

# Conclusion

当前收口后的契约验证通过。插件日志线上读写、WA 线上只读、CLI 本地校验、单体/合集 dry-run、Release 一致性和 Go 测试均有真实结果；未执行的 WA 线上写入及后续大 change 能力已明确列为跳过或限制，不计作已通过。
