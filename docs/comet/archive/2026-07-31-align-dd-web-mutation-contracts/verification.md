# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-228d83f231eb3dfa4b331221aafe6af9757d1e678ee126531245699ac3a03d3f",
    "evidence_refs": [
      "fupload/scripts/tests/test_builders.py",
      "fupload/scripts/tests/test_schema.py"
    ]
  },
  {
    "acceptance_id": "acceptance-2683a243642a87fc5d2452d22b2137107af6f377f139c8993d72b4cea0cf7b9c",
    "evidence_refs": [
      "fupload/scripts/tests/test_dd_session.py",
      "publish/20260801-064532-dd-web-mutation-alignment/01-plugin-create.json"
    ]
  },
  {
    "acceptance_id": "acceptance-2937ce2f7abab11fec7ea36f4a280e9d0996694ea0644840f488de455284236c",
    "evidence_refs": [
      "fupload/scripts/tests/test_builders.py",
      "publish/20260801-064532-dd-web-mutation-alignment/05-config-update-output.json"
    ]
  },
  {
    "acceptance_id": "acceptance-3d2521fa78ed0d4312543bf5cb38de4553b8d4606307a18461a670f99f5ac87b",
    "evidence_refs": [
      "fupload/scripts/tests/test_builders.py",
      "publish/20260801-064532-dd-web-mutation-alignment/02-plugin-update-output.json",
      "publish/20260801-064532-dd-web-mutation-alignment/03-plugin-edit-output.json"
    ]
  },
  {
    "acceptance_id": "acceptance-6c9ae907b5ea90b558e4ad43b216ff298f4df3001606edf3b86dfd40b9fabb00",
    "evidence_refs": [
      "fupload/scripts/tests/test_dd_session.py"
    ]
  },
  {
    "acceptance_id": "acceptance-7fa64efce3cf754c3f34931c4d59d0eb1a4a07aa55161f50268ef1140e9f490f",
    "evidence_refs": [
      "publish/20260801-064532-dd-web-mutation-alignment/read-matrix.json",
      "publish/20260801-064532-dd-web-mutation-alignment/verification.json"
    ]
  },
  {
    "acceptance_id": "acceptance-99d5cfda52dc8c853751f904b20d23c58793bd829abb686bda5495ff932f84c2",
    "evidence_refs": [
      "fupload/scripts/tests/test_builders.py"
    ]
  },
  {
    "acceptance_id": "acceptance-b1b2040565821aa71b3b1e1613b138254373f740431cd363d40243df2335af55",
    "evidence_refs": [
      "fupload/scripts/tests/test_builders.py",
      "publish/20260801-064532-dd-web-mutation-alignment/07-wa-create-output.json",
      "publish/20260801-064532-dd-web-mutation-alignment/08-wa-update-output.json",
      "publish/20260801-064532-dd-web-mutation-alignment/09-wa-edit-output.json"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `python -m unittest discover -s fupload\scripts\tests -v`: exit 0，142 tests passed。
- `python -m compileall -q fupload\scripts`: exit 0。
- `git diff --check`: exit 0；仅输出 Git 的 CRLF 转换提示。
- `python fupload\scripts\fupload.py dd session doctor`: exit 0；官方目录与签名有效，GUI 未运行，doctor 未登录。
- 非探索赛季动态只读矩阵：5 个 game type 全部完成 game versions、plugin/config/WA list、WA category 和 association GET。
- 最终真实写矩阵：一个 DD 原生登录会话内，plugin/config/WA 的 create、update、edit、delete 与读回全部 exit 0；三个临时 SN 均清理；session stop exit 0。

# Skipped checks

- 探索赛季真实写验证按用户明确非目标跳过。
- 未修改用户已有正式对象；真实写只使用本轮隔离私有对象。

# Spec consistency

实现、Schema、CLI help、Skill、DD reference 和拟议 `dd-publishing` 完整规格一致。插件修改按 author item 与 detail 的官方投影顺序构建，配置和 WA 保持各自 builder；错误日志、分页、上传 descriptor、条件字段、读回和会话生命周期均有合同测试及真实证据。

# Known limitations and risks

- `/addon/addon_versions` 对部分私密对象可能为空，因此只作为非空历史的重复版本门禁。
- mutation 后读回采用有界 GET-only 轮询；窗口内两个官方投影均未反映字段时仍返回 `verification_required=true`，不会自动重发。
- 真实矩阵覆盖当前环境返回的五个非探索 game type，只在具备完整依赖的正式服备份上执行配置写验证。

# Conclusion

通过。全部验收项都有直接项目证据，静态检查和真实单登录矩阵均成功，没有未解释的 blocking finding。
