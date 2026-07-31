# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-384f2561cf884e1144b69c3f1fbd72b2a51813735cc9aeea9e91e372e035f690",
    "evidence_refs": [
      "fupload/references/newbee-official-cli.md",
      "fupload/scripts/tests/test_cli.py"
    ]
  },
  {
    "acceptance_id": "acceptance-556062af80816b25f312069f6cea209e011bd9879748a66fe981243926353554",
    "evidence_refs": [
      "fupload/SKILL.md",
      "fupload/scripts/tests/test_cli.py"
    ]
  },
  {
    "acceptance_id": "acceptance-80c4ce1dafc5c3f77dc4935b24e192e3fced01a398556abdac2cb6fb27521f7a",
    "evidence_refs": [
      "README.md",
      "fupload/SKILL.md",
      "fupload/references/newbee-official-cli.md",
      "fupload/scripts/tests/test_cli.py"
    ]
  },
  {
    "acceptance_id": "acceptance-c35a2a4128a25febd90e74a846602420f2a088a59efc54a488a07d5008223de1",
    "evidence_refs": [
      "fupload/SKILL.md",
      "fupload/references/workflow.md",
      "fupload/scripts/tests/test_cli.py"
    ]
  },
  {
    "acceptance_id": "acceptance-d5b31e8dcbc8855cca3390dd32b904d119143dcc29a1a9b6af46d13a35b22ae5",
    "evidence_refs": [
      "fupload/SKILL.md",
      "fupload/references/newbee.md",
      "fupload/references/workflow.md",
      "fupload/scripts/tests/test_cli.py"
    ]
  },
  {
    "acceptance_id": "acceptance-db351c4b4c976137f358910d94145ebdf1dd5cfe71b8ef9ec92810ba05495e24",
    "evidence_refs": [
      "README.md",
      "fupload/SKILL.md",
      "fupload/scripts/tests/test_cli.py"
    ]
  },
  {
    "acceptance_id": "acceptance-fb6c69eacbd1783e1bc0e57e9cae44cdaa4cdf25b9bb6e483948975751d103ad",
    "evidence_refs": [
      "fupload/SKILL.md",
      "fupload/agents/openai.yaml",
      "fupload/references/workflow.md",
      "fupload/scripts/tests/test_cli.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `curl.exe -fsSL https://creator.newbeebox.com/md/cli-docs` -> 官方 UTF-8 Markdown 获取成功；复制后的正文逐字符比较为 `OfficialBodyExact=True`，来源 URL、日期和运行时优先规则位于引用头部；exit 0。
- `npm i -g @newbeebox/newbeebox-creator-center-cli@latest` -> `added 2 packages`; exit 0。
- `node -v` -> `v24.13.1`; exit 0。`ncc -V` -> `0.1.29`; exit 0。
- `ncc --help` 与 `ncc docs` -> 均成功；exit 0。环境检测确认 `NCC_TOKEN` 不存在。
- `ncc whoami -o json` -> stdout 为 `{"error":"auth_failed","message":"未登录。请先运行：ncc login"}`；exit 2，符合官方鉴权失败契约，未提示或输出任何真实令牌。
- `ncc wow addons create --help`、`addons push --help`、`wa publish --help`、`uipack push --help`、`cloudbackup info --help` -> 全部 exit 0；确认插件 push 暴露 `--dry-run`，其他叶子不被 Skill 伪造 dry-run。
- `python -m unittest discover -s fupload\scripts\tests -v` -> `Ran 92 tests ... OK`; exit 0。新增断言覆盖默认官方路由、显式第三方选择、无静默 fallback、安装/身份命令、完整文档章节与凭据规则。
- `python -m compileall -q fupload\scripts` -> 无诊断；exit 0。
- `git diff --check` -> 无空白错误；exit 0。Git 仅输出仓库既有的 LF/CRLF checkout 警告。
- 对 `analyze/` 与 `.git/` 之外项目文件执行长 `ncc_` 令牌模式扫描 -> `LongTokenPatternHits=0`; exit 0。
- `comet native check prefer-newbee-official-cli --json` -> 7 个实现文件、69,254 字节、0 问题；receipt `runtime/evidence/check-receipts/cc748dc7fea888ca88b158fae65f8b146bcb16598fe79b3c1b80a39f2f785382.json`; exit 0。

# Skipped checks

- 已登录账号的 `ncc whoami -o json` 成功路径未执行。本轮对话中出现过的明文令牌按确认约束视为待吊销凭据，没有传给工具；验证使用无 `NCC_TOKEN` 的干净环境确认鉴权失败路径。
- 未执行插件、WA 或配置分享的官方线上写入。本 change 的目标是 Skill 路由、文档和凭据交付契约，brief 明确排除修改正式线上内容；真实写入需用户建立新的本机官方登录态并另行确认具体发布计划。
- 未测试探索赛季，延续用户已确认的排除范围。

# Spec consistency

- `fupload/SKILL.md` 先检测本机 `ncc`：存在即默认官方通道；缺失时先询问再安装；只有用户显式要求第三方 Python 管理工具才使用 bundled CLI。
- 官方能力缺口不自动 fallback。切换通道前必须重新读取远端状态并重新确认计划，避免重复创建或上传。
- 官方通道读取完整静态参考，并在每次执行时以已安装 `ncc docs` 和叶子 help 为准；Python NewBee 字段参考已明确标为第三方专用。
- 凭据优先使用官方本机登录或调用环境预置 `NCC_TOKEN`。真实值不进入对话复述、命令参数、计划 JSON、日志、测试、Skill/reference 或 Git；`whoami` 仅保留任务所需身份与权限。
- 官方与 Python 通道都保留项目内 `publish/` JSON 记录；官方记录是脱敏计划而非伪造的 Python `--input`，原始 WA/配置内容只保存文件引用。
- DD 路由、Python schema/provider 和探索赛季约束未改变。

# Known limitations and risks

- 官方 HTTP Markdown 与安装版 `ncc docs` 0.1.29 的标题、排版和章节展开并非逐字一致：HTTP 版本 281 行，运行时版本 300 行。项目按需求保存 HTTP 端点完整正文，同时明确运行时 docs/help 优先，避免静态快照覆盖已安装版本。
- 官方 CLI 功能仍可能受账号内测权限、平台限额和版本门禁影响。Skill 对 `cli_not_authorized`、`cli_disabled`、`quota_exceeded` 等结果按官方文档停止，不循环重试。
- 官方 `ncc` 已全局安装到当前 Windows 用户的 npm 目录。它不是仓库产物，也不携带登录态；后续可通过 npm 正常升级或卸载。

# Conclusion

Pass。7 条验收项均有直接项目证据；官方文档正文完整，默认路由和凭据边界已固化，92 项回归与 scoped text check 通过，项目中没有长格式 CLI 令牌。
