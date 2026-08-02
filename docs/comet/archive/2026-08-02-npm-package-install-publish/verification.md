# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-12fd31a2b9bc9407e927bdf7b4b8550a931eff625f06d23880d457a279486f54",
    "evidence_refs": [
      "npm/lib/uninstall.mjs",
      "npm/scripts/test-install.mjs",
      "npm/test/uninstall.test.mjs"
    ]
  },
  {
    "acceptance_id": "acceptance-2e537f56365d0c006953215b7297d380d9adcf4d0205294ccabd92fe7b4d2454",
    "evidence_refs": [
      "npm/lib/update.mjs",
      "npm/test/uninstall.test.mjs"
    ]
  },
  {
    "acceptance_id": "acceptance-65652e0ab61390ae239ff3ad08a307c60e6bf176081969673faf54cafe77759c",
    "evidence_refs": [
      "npm/bin/fupload.mjs",
      "npm/scripts/test-install.mjs"
    ]
  },
  {
    "acceptance_id": "acceptance-826dfd1ae4aefd4fd0c2cfa7b8aed9719d3c954dd997ea27a6bd5e496b5615f2",
    "evidence_refs": [
      "npm/lib/uninstall.mjs",
      "npm/test/uninstall.test.mjs"
    ]
  },
  {
    "acceptance_id": "acceptance-89bb2a4dc9f61f3ae727b207955099ec5788ebbb145a958b82a39eef7556b963",
    "evidence_refs": [
      ".github/workflows/publish-npm.yml",
      "npm/scripts/test-install.mjs"
    ]
  },
  {
    "acceptance_id": "acceptance-df34e4e24063a60e68e761aa3e063647a762fd92882c46bb5d82d2fc90c3523b",
    "evidence_refs": [
      "npm/lib/skill-installer.mjs",
      "npm/lib/update.mjs",
      "npm/test/skill-installer.test.mjs"
    ]
  },
  {
    "acceptance_id": "acceptance-f7e44e7b2572b0dcab2e9a2d979a5063f2288ea4fd3d515b8c96d6c3a4db9f80",
    "evidence_refs": [
      "npm/scripts/verify-package.mjs",
      "package.json"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `npm run check:versions`：通过，package、lock、Skill metadata、Python CLI 与 manifest 均为 `0.0.1`。
- `npm run check:release -- v0.0.1`：通过，tag 契约匹配。
- `npm test`：17 项 Node 测试通过，覆盖路径解析、Python 发现、manifest 校验、原子安装/升级、路径登记、未知目录保护、清理失败、update 与自卸载命令。
- `npm run check:manifest`：通过，manifest 为 31 个运行时 Skill 文件。
- `npm run test:pack`：通过，tarball 为 43 个文件、114289 bytes，不含测试、缓存、Comet、analyze、publish 或凭据形态内容。
- `npm run test:install`：通过，在隔离 npm prefix 中完成正常与 `--ignore-scripts` 两组真实全局安装、`fupload --version`、Python help、默认/自定义 Skill、`fupload uninstall`，确认 CLI、npm 包、全部受管 Skill 与 npm 登记状态均删除，项目 `publish/` 记录哈希不变。
- `python -m unittest discover -s fupload/scripts/tests -v`：212 项通过。
- `python -m compileall -q fupload/scripts`：通过。
- 对全部 `npm/**/*.mjs` 运行 `node --check`：通过。
- 使用 PyYAML 读取 `.github/workflows/publish-npm.yml`：通过，包含 `test` 与 `publish` jobs。
- `npm publish --dry-run --json`：通过，公开包元数据和 43 文件 inventory 正常。
- `npm audit --audit-level=high`：通过，0 个漏洞。
- `git diff --check`：通过。
- `comet native check npm-package-install-publish`：通过，receipt `runtime/evidence/check-receipts/912625a6c3deb2c0b95aee6cd8b4d56953298acd06b56d2c26a61df4c678e050.json`。

# Skipped checks

- GitHub 托管的 Windows/Linux jobs 尚未执行；workflow 需要先提交并推送。
- npm OIDC 正式发布尚未执行；新包需要先建立包身份并在 npm 页面绑定 Trusted Publisher。
- `fupload update` 尚未对真实 registry 的 `latest` 执行；首个正式版本发布前不存在可更新目标。固定包名、prefix、npm-cli 调用和全部受管 Skill 同步已由 Node 测试覆盖。

# Spec consistency

实现与确认后的 `npm-distribution` 规格一致：npm 安装提供统一 `fupload` 入口；版本载体统一；update 固定更新官方包并同步受管 Skill；uninstall 不依赖 npm lifecycle，先清理受管 Skill再删除自身；未知目录、项目发布记录、平台凭据和日志保持不变；tag workflow 使用最小 OIDC 权限并在跨平台测试后发布。

# Known limitations and risks

- npm 首次包身份建立和 Trusted Publisher 绑定属于外部平台步骤，需要 npm 账号所有者在页面完成；仓库不保存长期 token。
- 直接 `npm uninstall -g @follenfang/fupload` 受 npm 7+ 行为限制，只删除 npm 包和 CLI；README 与 Skill 明确要求使用 `fupload uninstall` 完整卸载。
- Python 业务能力仍受目标桌面客户端和线上接口版本影响，本 change 未改变这些平台契约。

# Conclusion

通过。实现范围内的安装、运行、更新、完整卸载、版本一致、包内容与发布 workflow 均有自动化证据；外部发布步骤在代码提交后继续执行。
