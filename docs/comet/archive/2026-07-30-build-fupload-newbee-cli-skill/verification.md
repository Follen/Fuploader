# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-192f996e4613da710fe53c10a55b64a9220fc020578c5c599e954349da74f71b",
    "evidence_refs": [
      "Release/fupload/SKILL.md",
      "internal/newbee/service_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-20b902a219b424aa1b0b25d85685de6fc5e0c90b105f1e8538df9ef191796e7c",
    "evidence_refs": [
      "Release/fupload/SKILL.md",
      "internal/newbee/service_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-21caee4f8aa62afe2228ba62536c3ca411dc9d35ac4863abca74a1702666141b",
    "evidence_refs": [
      "Release/fupload/SKILL.md",
      "internal/newbee/service_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-5b017ff91863e975cb1d801040ad1a25c366f66ba6ee2e5ec362444b180814f3",
    "evidence_refs": [
      "internal/cli/root_test.go",
      "internal/platform/platform_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-66ba65e3788175d8ea36c47b0fbe1992b37f5093fe4e44d17615fa9781573f46",
    "evidence_refs": [
      "Release/fupload/references/plugin.md",
      "internal/newbee/service_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-7c079bedca25d6865242245ab2aa4276737537b68fdecadf5669bf79f18165f8",
    "evidence_refs": [
      "Release/fupload/references/config.md",
      "internal/newbee/service_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-8ece9b060911081c25c7104cff3505cab123d83469b129a8e438b4d9d4fd5aa8",
    "evidence_refs": [
      "Release/fupload/SKILL.md",
      "internal/newbee/service_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-958caeeafc82b122ec5f6c23ee9e099753437f784aa0596ef434a6f243aa929e",
    "evidence_refs": [
      "Release/fupload/SKILL.md",
      "internal/newbee/service_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-a674949bdc7b3dfc4b018cd090fd35c530b3f62662eb3792607611e9500bfaa2",
    "evidence_refs": [
      "internal/cli/root.go",
      "internal/cli/root_test.go"
    ]
  },
  {
    "acceptance_id": "acceptance-b973f5926ac13604f85f9ebfe89b90131560d5f54133dabc76ae6c7b63fbbee5",
    "evidence_refs": [
      "newbee.md"
    ]
  },
  {
    "acceptance_id": "acceptance-d3db079048ba7b14f057b03a7384dfd07abb2bea9c0a1e6254c48af50be6a4de",
    "evidence_refs": [
      "newbee.md"
    ]
  },
  {
    "acceptance_id": "acceptance-fa8e66d54b1411f96b1972a1504319a6569d5d5307763c8b509d9cb804f523a1",
    "evidence_refs": [
      "internal/cli/root.go",
      "internal/platform/platform.go"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `go test ./...`: passed for all CLI, input, NewBee adapter, platform and Skill packages.
- `go test -race ./...`: passed, including authentication and request code.
- `go vet ./...`: passed.
- `node --test newbee/auth-state.test.mjs newbee/creator-auth.test.mjs newbee/creator-content.test.mjs`: 5 tests passed.
- `uv run --with pyyaml python .../quick_validate.py Release/fupload`: `Skill is valid!`.
- `go build -trimpath -o bin/fupload.exe ./cmd/fupload`: passed.
- `go build -trimpath -o Release/fupload/bin/fupload.exe ./cmd/fupload`: passed; root and release binaries have SHA-256 `E3DE2C2ED7A0F54E63A7F4D02964A5568FADE07EF22987DA3D1AA23A4D6C1428`.
- `Compress-Archive -Path Release/fupload -DestinationPath Release/fupload.zip -Force`: passed; ZIP SHA-256 is `548ECAC140656F98EBE41C45A99C14A1DD055B7118B7CF1335BFDE2F0E586826`.
- The packaged executable was run from outside the repository. `plugin list`, `backup list`, and `config list` all returned `success=true`; current totals were 4 plugins, 2 backups, and 0 config shares.
- `fupload newbee plugin publish-version --help` from the packaged executable described required fields, archive limits, multi-game-version behavior, dry-run and review semantics.
- The recorded controlled online audit created plugin 24410, published a version, submitted it for review, published version `2026.07.30-audit.1` to plugin 20745, edited and restored its metadata, and created/updated/switched-backup configuration shares with read-after-write checks.

# Skipped checks

- Destructive delete endpoints were not tested because deletion is outside the accepted scope.
- Online writes were not repeated during this final verification; the existing 2026-07-30 controlled audit evidence in `newbee.md` was used to avoid duplicate versions and review submissions.
- `comet native check` was not used as pass evidence because the accepted partial scope contains unrelated DD and removed adapter paths; targeted project tests and Skill validation cover the Fupload artifacts directly.

# Spec consistency

The CLI exposes the accepted NewBee plugin, backup, config and option command set with strict structured input, stable JSON output, atomic writes and review-state wording. The distributed Fupload Skill covers the five user intents, one confirmation, read-after-write verification, failure stop behavior and client-uploaded backup prerequisite. The `dd` platform ID is reserved and returns an explicit unsupported result.

# Known limitations and risks

- The implementation scope uses the user-confirmed partial allowance only for removed non-Codex adapters and concurrent DD work, which belongs to a separate change. Fupload source, tests, examples, audit records, binaries and release package are declared artifacts.
- NewBee uses undocumented endpoints; later server-side field changes can still require adapter updates. HTTP and business-code failures are surfaced without credentials.
- The current account has no surviving config share to read in the final smoke test; config request/merge behavior is covered by local HTTP contract tests and the earlier controlled online audit.

# Conclusion

Pass. The complete Fupload implementation and distributable package satisfy the confirmed contract.
