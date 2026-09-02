---
generated_from_state_version: 15
---

# Verification

## Current result

- Result: **Passed**
- Assurance: **skill-coordinated**
- Goal cycle: 2
- Iteration: 1
- Verifier attempt: 1
- Completed: 2026-08-26T09:44:33.742Z
- Summary: Independent read-only verification passes A1-A20 for candidate 6520b6717dbec8d1920c501349c8db517b4731df / v0.0.15. Current Creator and main evidence hashes match the final regenerated files; all live CRUD, full-field matrices, binary media and ZIP paths, Builds 0..4, cleanup, test gates, GitHub CI, Trusted Publishing, npm registry and isolated installation checks pass.

## Acceptance

| ID | Result | Source | Criterion | Reason |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1：Creator 与主程序两个 `session doctor` 均真实复用对应本机登录态并得到 `api_ready=true`，输出只含脱敏布尔状态。 | Creator and main session doctor both returned api_ready=true using their separate local sessions; only readiness booleans and key names were retained. |
| A2 | passed | brief.md | A2：Creator 项目字段矩阵完整覆盖名称、别名、摘要、分类、同步、ModUs/大脚至少一项、tier、仓库、依赖、许可证全部子字段、logo/screenshot、图片操作及服务端只读字段；每个可写字段均有真实修改/回读/恢复/再回读记录。 | Creator evidence covers the complete project field matrix, state ordering, at-least-one platform rule, no-tier path, license subfields, dependencies, repository, images, and per-field mutate/read/restore cycles. |
| A3 | passed | brief.md | A3：Creator 项目真实 create/detail/edit/delete；项目 logo/screenshot 创建与图片 upload/delete edit 均提交真实图片内容并回读服务端图片状态。 | Real project create/detail/edit/delete and logo/screenshot create, replace, rename, delete, restore and server readback succeeded; logo CDN returned 404 after project deletion. |
| A4 | passed | brief.md | A4：Creator 插件版本字段矩阵完整覆盖 project/file ID、version、type、支持游戏版本、MD5、ZIP/解压大小、对象路径、TOC、changelog；create/upload/update/edit/delete 均真实执行，ZIP 原始字节 PUT、写后回读和最终清理成功。 | Release and ZIP fields plus real create/upload/update/edit/delete, original-byte PUT, MD5/size/TOC/version readback and final not-found cleanup are evidenced. |
| A5 | passed | brief.md | A5：`modus builds` 返回 Build 0..4；每个 Build 的 backup/config/WA 列表均真实成功，`server` 与 `X-Server-Type` 同步，任何业务 500 必须定位字段并修正，不能当空结果。 | Builds 0 through 4 each completed backup/config/WA listing with exit 0; body server and X-Server-Type stay synchronized and business errors remain errors. |
| A6 | passed | brief.md | A6：配置分享字段矩阵完整覆盖分页/过滤字段及 `addonsId`、`backupId`、账号/角色、HTML/纯文本正文、`imageUrl`、公开/付费/价格、分享类型、标签、标题、WTF 排除、tier、subType、platform、synchronizationType、Build；每个可写字段真实修改/回读/恢复/再回读。 | All 18 configuration field checks passed with real create/update/detail/filter/delete and mutate/restore cycles; non-returned fields have explicit observable semantics. |
| A7 | passed | brief.md | A7：配置本地图片通过主程序真实二进制上传取得服务端引用；该引用分别用于配置 create 和 update，detail 回读匹配；随后配置 delete 并验证软删除和活动列表缺失。 | Two real local binaries produced server media references used by config create and update, matched detail readback, and the config was soft-deleted and excluded from active lists. |
| A8 | passed | brief.md | A8：WA/字符串字段矩阵完整覆盖分页/过滤字段及适用插件、封面&图片、标签、版本号、codeText、HTML/纯文本正文、同步到大脚、tier、公开/付费/价格、shareType、subType、platform、synchronizationType、Build；每个可写字段真实修改/回读/恢复/再回读。 | All 22 WA/string field checks passed across article, code, addon, tag, version, publication, payment, synchronization, platform, tier and Build fields. |
| A9 | passed | brief.md | A9：WA 本地图片通过主程序真实二进制上传取得服务端引用；该引用分别用于 WA create 和 update，detail 回读匹配；WA version publish/detail/delete 与 WA delete 均真实完成并最终清理。 | WA media create/update/detail, three real version publications with digest readback, version cleanup, article soft-delete and active-list exclusion are evidenced. |
| A10 | passed | brief.md | A10：所有下拉/枚举/联动分支有正负向证据，包括分类、游戏版本、适用插件、标签、同步模式、平台至少一项、WTF 与账号/角色、tier=无、付费/价格、Build 0..4；非法组合在远端写入前失败。 | Positive and negative matrices cover dropdowns, at-least-one choices, BigFoot linkage, game/addon/tag options, WTF account/role, no tier, fixed-free payment, image limits and all Builds; invalid combinations exit 2 before mutation. |
| A11 | passed | brief.md | A11：真实证据逐步保存命令、脱敏输入摘要、响应摘要、退出状态，以及正文/图片/ZIP 的长度和 SHA-256；证据能证明写入与回读使用同一内容，又不泄漏原文或签名材料。 | Both evidence files record commands, redacted inputs/responses and exits; mutable text, code, changelog, images and ZIPs use byte counts and SHA-256 without credentials, signatures or account/role values. |
| A12 | passed | brief.md | A12：全量 Python/Node、编译、manifest、tarball、隔离安装和脱敏扫描通过；最终代码与文档推送 GitHub，发布高于 `0.0.12` 的新 npm 版本，tag/registry/latest/全局安装版本一致。 | Python 346, Node 26, compile, manifest, versions, 55-file tarball, isolated install and redaction gates passed; GitHub, tag, npm latest and installed CLI all report 0.0.15. |
| A13 | passed | specs/modus-full-field-regression/spec.md | Fupload SHALL reuse the separate local authenticated sessions of ModUs.Creator and the ModUs main client. It SHALL expose diagnostic readiness without returning credentials. Creator project/plugin requests SHALL use the Creator session; configuration, WA/string and main-media requests SHALL use the main-client session. | Implementation separately reuses Creator DPAPI token storage and main-client LevelDB state; each API family uses the correct client and diagnostics expose no credential material. |
| A14 | passed | specs/modus-full-field-regression/spec.md | Fupload SHALL model every Creator project field exposed by the installed client, including state-machine ordering, dropdown enums, at-least-one platform selection, the real no-tier branch, all license subfields, dependencies, repository, logo/screenshot creation payload and edit image operations. A real regression SHALL mutate every writable field independently, read it back, restore it and read the restoration back. Local project images SHALL be submitted through the exact official create or edit image wire form and their server-managed result SHALL be read back. | Creator schema, state machine, dynamic enums, no-tier branch, license/dependency fields, media protocol and live per-field evidence satisfy the complete project model. |
| A15 | passed | specs/modus-full-field-regression/spec.md | Fupload SHALL support project and release discovery plus real release create, upload, update, metadata edit and delete. It SHALL derive and submit the exact ZIP metadata, allocate a file ID, obtain a signed upload URL, PUT the original ZIP bytes, read back all release fields and clean up in dependency order. Evidence SHALL bind the ZIP input to the uploaded object with length and SHA-256 while removing signed URL material. | File-ID allocation, derived ZIP metadata, signed-upload allocation, original ZIP PUT, full readback and dependency-ordered cleanup are evidenced while signed URLs are omitted. |
| A16 | passed | specs/modus-full-field-regression/spec.md | Fupload SHALL expose all confirmed Build IDs and use the selected Build consistently in request body `server` and `X-Server-Type`. Backup, configuration and WA/string list operations SHALL run successfully for each Build with exact official defaults and filters. Business error responses SHALL remain errors. | Implementation, unit tests and live evidence jointly confirm all five Builds, synchronized body/header values, official defaults and successful backup/config/WA lists. |
| A17 | passed | specs/modus-full-field-regression/spec.md | Fupload SHALL model all official configuration list and write fields, their types, defaults, enums and interdependencies. It SHALL upload a local cover/image using the official main-client binary image protocol, extract the reusable server reference, use it in real create and update requests, and verify the detail response. Every other writable configuration field SHALL undergo the same mutate/read/restore/read cycle. Delete success SHALL follow the service's soft-delete semantics and active-list exclusion. | Complete config schema and dynamic validation, official multipart media upload, real field cycles, detail verification and soft-delete semantics all passed. |
| A18 | passed | specs/modus-full-field-regression/spec.md | Fupload SHALL model all official WA/string list, article, code, version, applicable-addon, tag, publication, payment, synchronization, platform, tier and Build fields. It SHALL upload a local cover/image using the official main-client binary image protocol, use the returned reference in real create and update requests and verify the detail response. It SHALL also publish, read and delete a real version and finally soft-delete the test article. | Complete WA/string schema, media use, real version publish/read/delete and final article soft-delete all passed. |
| A19 | passed | specs/modus-full-field-regression/spec.md | Documentation SHALL contain complete Creator project/release, configuration and WA/string field matrices with CLI name, wire name, JSON type, required/default behavior, enum source, state dependency, write endpoint and readback location. Positive and negative regression SHALL cover dropdown values, empty/null branches, mutually constrained fields, at-least-one selections, current no-tier behavior and all Builds. Invalid combinations SHALL fail before remote mutation. | modus.md contains seven complete Creator project/release/config/WA/version/media matrices with CLI, wire, type, default, enum, linkage, endpoint and readback columns plus positive/negative coverage. |
| A20 | passed | specs/modus-full-field-regression/spec.md | Real regression evidence SHALL be generated against the final implementation and record each command, redacted input summary, response summary and exit status. Mutable content, image and ZIP inputs SHALL include length and SHA-256 rather than raw bytes/text. The final release SHALL be newer than 0.0.12, pushed to GitHub, pass Windows and Ubuntu CI plus Trusted Publishing, match the npm registry/latest version and install globally. | Final evidence hashes are 7C7BE87959024A1431BC154B13830178815FFF32D23D55E4EAAED75B96B56E4B and 298CD33D8E9B72E5AE7B63B6A82627622493CB2DC7476AFE61434E395312BB78; commit, origin/main, v0.0.15, CI, Trusted Publishing, npm exact/latest and isolated install agree. |

## Checks

| Check | Command | Working directory | Status | Exit | Duration |
| --- | --- | --- | --- | ---: | ---: |
| full Python unittest suite | -m unittest discover -s fupload/scripts/tests -q | . | passed | 0 | 13024 ms |
| full Node test suite | test | . | passed | 0 | 78100 ms |
| Skill manifest consistency | run check:manifest | . | passed | 0 | 652 ms |
| release version consistency | run check:versions | . | passed | 0 | 642 ms |
| package inventory and credential scan | run test:pack | . | passed | 0 | 1407 ms |
| isolated install runtime launch and uninstall | run test:install | . | passed | 0 | 171809 ms |
| compile Python sources | -m compileall -q fupload/scripts | . | passed | 0 | 104 ms |
| Creator and main live evidence identity | -c import hashlib,json,pathlib; a=pathlib.Path('analyze/modus-creator/iteration4-live-regression.json'); b=pathlib.Path('analyze/modus/live-main-crud-builds-20260826.json'); x=json.loads(a.read_text(encoding='utf-8')); y=json.loads(b.read_text(encoding='utf-8')); assert hashlib.sha256(a.read_bytes()).hexdigest().upper()=='7C7BE87959024A1431BC154B13830178815FFF32D23D55E4EAAED75B96B56E4B'; assert hashlib.sha256(b.read_bytes()).hexdigest().upper()=='298CD33D8E9B72E5AE7B63B6A82627622493CB2DC7476AFE61434E395312BB78'; assert x['result']=='passed' and len(x['steps'])==140; assert y['result']=='passed' and len(y['steps'])==209 and len(y['field_checks'])==40 and len(y['builds'])==5 | . | passed | 0 | 89 ms |
| HEAD origin and peeled v0.0.15 tag identity | -NoProfile -Command $h=git rev-parse HEAD; $o=git rev-parse origin/main; $t=git rev-parse 'v0.0.15^{}'; if($h -ne '6520b6717dbec8d1920c501349c8db517b4731df' -or $o -ne $h -or $t -ne $h){exit 1}; Write-Output "HEAD=$h origin=$o tag=$t" | . | passed | 0 | 331 ms |
| GitHub Windows Ubuntu and Trusted Publishing run | run view 32950297622 --repo Follen/Fuploader --json status,conclusion,headSha,url,jobs | . | passed | 0 | 1593 ms |
| npm registry exact and latest version | view @follenfang/fupload@0.0.15 version dist-tags --json | . | passed | 0 | 1677 ms |

## Blockers

_None._

## Risks and skipped work

- backup_id had one live candidate and is recorded as dynamic_singleton.
- role_name is service_ignored and content_text is write_accepted_not_returned; evidence uses presence or body digests for their observable behavior.
- There is no GitHub Release page object; the required pushed tag, CI and npm publication are complete.

## Previous iterations

| Goal cycle | Iteration | Attempt | Outcome | Unresolved | Summary | Completed |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1 | 1 | fail | A4, A5, A6, A7, A8 | A1-A3 通过；A4-A8 未满足。必须回 Build 修正 addonsId 类型、platform/synchronizationType/excludeWtf 默认与规范化，重跑真实 CRUD/版本，然后完成 GitHub 与 npm 发布。 | 2026-08-25T18:24:05.056Z |
| 1 | 2 | 1 | pass | — | A1-A8 all passed after implementation and release. Runtime checks, independent evidence audit, GitHub workflow, npm registry and real global installation all agree on candidate d73eacf / version 0.0.12. | 2026-08-25T19:45:40.908Z |
| 1 | 2 | 1 | recovery | — | 用户明确要求全字段真实回归；当前验收遗漏 Creator 项目图片、配置封面和 WA/字符串封面二进制上传及其字段闭环，0.0.12 不构成最终验收。退回需求修订，补齐三类图片上传、所有字段逐项修改回读恢复、完整真实 CRUD 和重新发版。 | 2026-08-26T03:07:01.246Z |
| 2 | 1 | 1 | pass | — | Independent read-only verification passes A1-A20 for candidate 6520b6717dbec8d1920c501349c8db517b4731df / v0.0.15. Current Creator and main evidence hashes match the final regenerated files; all live CRUD, full-field matrices, binary media and ZIP paths, Builds 0..4, cleanup, test gates, GitHub CI, Trusted Publishing, npm registry and isolated installation checks pass. | 2026-08-26T09:44:33.742Z |

## Conclusion

Independent read-only verification passes A1-A20 for candidate 6520b6717dbec8d1920c501349c8db517b4731df / v0.0.15. Current Creator and main evidence hashes match the final regenerated files; all live CRUD, full-field matrices, binary media and ZIP paths, Builds 0..4, cleanup, test gates, GitHub CI, Trusted Publishing, npm registry and isolated installation checks pass.
