# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-06cb318caef24f597626fa64df88ac6f1b5677534f571cad21e71cca3b9e8b14",
    "evidence_refs": [
      "fupload/references/dd.md",
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/dd_sidecar.py",
      "fupload/scripts/tests/test_builders.py"
    ]
  },
  {
    "acceptance_id": "acceptance-149e9e96b473754cf3e30199da4cdf645488b366ecac21f91fb302f4d6792177",
    "evidence_refs": [
      "fupload/SKILL.md",
      "fupload/agents/openai.yaml",
      "fupload/scripts/fupload.py",
      "fupload/scripts/tests/test_cli.py"
    ]
  },
  {
    "acceptance_id": "acceptance-1631f14f63126a53597368fc14dbd7ed6a1326c24a74b61db859b3907e301b4c",
    "evidence_refs": [
      "fupload/references/dd.md",
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_builders.py"
    ]
  },
  {
    "acceptance_id": "acceptance-2c51103895c174e31b2a3c938851c8dde7a787f9043e2d208cf4ad8a7da0c091",
    "evidence_refs": [
      "fupload/references/dd.md",
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_builders.py",
      "fupload/scripts/tests/test_schema.py"
    ]
  },
  {
    "acceptance_id": "acceptance-54a4e0f54ce4a779d42c5f95b7a6f3317a023ffed387c432343e45e8a54c28e7",
    "evidence_refs": [
      "fupload/references/newbee.md",
      "fupload/scripts/fupload_cli/cli.py",
      "fupload/scripts/fupload_cli/newbee.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_builders.py"
    ]
  },
  {
    "acceptance_id": "acceptance-66c88505fcee93ffd8e828725960bb2fd811b00433f2fef6c2e58d94fa49fb7a",
    "evidence_refs": [
      "fupload/references/newbee.md",
      "fupload/scripts/fupload_cli/newbee.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_builders.py",
      "fupload/scripts/tests/test_schema.py"
    ]
  },
  {
    "acceptance_id": "acceptance-67ccd72f1ca06244ba5d2640e9e416bb7b7d42768f95667262bed045a33d97be",
    "evidence_refs": [
      "fupload/SKILL.md",
      "fupload/references/newbee.md",
      "fupload/references/workflow.md",
      "fupload/scripts/fupload_cli/newbee.py",
      "fupload/scripts/tests/test_builders.py"
    ]
  },
  {
    "acceptance_id": "acceptance-b52b3a86593c95e37728976a77256438243a110ac79d811a8cfe3d0532fd1c33",
    "evidence_refs": [
      "fupload/references/newbee.md",
      "fupload/scripts/fupload_cli/newbee.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_builders.py",
      "fupload/scripts/tests/test_schema.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f6c8894a3d2cb003500823d2a0cf4653888411f733ddaac9dd066d6721e2a877",
    "evidence_refs": [
      "fupload/references/dd.md",
      "fupload/references/newbee.md",
      "fupload/references/workflow.md",
      "fupload/scripts/tests/test_cli.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `python -m unittest discover -s fupload\scripts\tests` -> `Ran 59 tests ... OK`; exit 0.
- `python -m compileall -q fupload\scripts` -> no diagnostics; exit 0.
- `git diff --check` and `git diff --cached --check` -> no whitespace errors; exit 0. Git emitted only configured LF-to-CRLF checkout warnings.
- `python analyze\audit-live-matrix.py analyze\live-matrix-20260731100523-1b60f3\report.json` -> `status=passed`, `leaf_count=64`, `live_leaf_count=64`, `step_count=241`, `object_count=32`, no missing leaves or errors; exit 0.
- The normalized live matrix report `analyze/live-matrix-20260731100523-1b60f3/report.json` records real NewBee and DD plugin/config/WA create, update, edit and attached/read interfaces across the confirmed build matrix. Every successful write has a readback record.
- `python fupload\scripts\fupload.py newbee session doctor` -> authenticated from the desktop auth-store; exit 0.
- `python fupload\scripts\fupload.py dd session doctor` -> authenticated, selected validated DD version `100128`, and reported the DD-owned sidecar state path; exit 0.
- `python fupload\scripts\fupload.py newbee plugin game-versions` -> six current builds: retail, Titan Reforged, Mists of Pandaria, Burning Crusade, classic, and Season of Discovery; exit 0.
- `python fupload\scripts\fupload.py dd options game-types` -> five current builds: retail, Titan Reforged, Mists of Pandaria, Burning Crusade, and classic; exit 0.
- `python fupload\scripts\fupload.py dd options life-types` without `--game-type` -> six official client lifetime values; exit 0.
- `python -u analyze\cleanup-live-objects.py --inventory` -> manifest 38, present 34, absent 4, no ownership mismatch; exit 0.
- `python -u analyze\cleanup-live-objects.py --execute` -> `status=passed`, deleted 34, already absent 4, final absent 38, remaining 0; exit 0. The final report is `analyze/cleanup-report-20260731100523-1b60f3.json`.
- Prospective tracked-tree audit -> 53 files, no Go/EXE/DLL/ZIP artifacts, no tracked `analyze/` entries, no author absolute paths, and no credential literals. Four sensitive-word matches were code identifiers, redaction regexes, or test fixtures.

# Skipped checks

- NewBee Season of Discovery configuration create/update/edit was intentionally not executed because the current account has no matching cloud backup and the user explicitly excluded that build's configuration writes. Dynamic reads, plugin, and WA coverage still include that build.
- After the final cleanup reached 38/38 absent, the audit fixes were verified with focused regression tests and read-only live session/build checks. The full write matrix was not repeated because that would recreate the objects just removed; the pre-cleanup real-write report remains the production-chain evidence.
- `comet native check python-fupload-newbee-dd` did not produce text-safety evidence. Receipt `runtime/evidence/check-receipts/e9c08388d038591163b4e671b526599b74e89d379b7bd805a4d67584ecb12b9d.json` records one `scan-limit` on a deleted baseline minified asset (`newbee/creator/assets/Step4StringUpload-B_v8Qzpz.js`), zero files scanned, and fresh contract/scope hashes. The failed receipt is not cited as a passing check.

# Spec consistency

- The deliverable is only `fupload/` plus Native formal artifacts and project workflow metadata. Product code is pure Python under `fupload/scripts/`; Go sources, binaries, old release bundles, and exploration trees are deleted.
- Schema, CLI help, platform references, and provider mappings cover all create/update/edit fields and all 64 CLI leaves. Tests assert every schema field appears in the corresponding platform reference and every bundled example passes dry-run.
- NewBee update omission now preserves existing channel and WA title-array values. DD enabled channel/association inputs fail when live candidates are empty. DD discovery covers environment override, running process, uninstall records, bounded user JSON, and known roots, then selects the highest validated version unless explicitly pinned.
- The Native implementation scope is partial only because deleted top-level paths cannot be owned by an artifact that must still exist. Scope `5654d5a09359b542f0556807d0bdabefd863e8f17b590c73cb7c3acfd22ed231` contains the complete physical projection and allowance `102869b0658b347bea399961fbf9a4dd25489af28b4a98366bf782cfe0e26d39` records this structural limitation.

# Known limitations and risks

- Both providers depend on current third-party desktop authentication and production API shapes. Dynamic reads fail closed when required choices disappear; future client/API changes may require a schema or adapter update.
- DD requires Windows and a compatible official client. POST/upload response timeout is reported as `verification_required`; the caller must perform a new read-only command before deciding whether to retry.
- Test exploration and detailed live reports are intentionally ignored under `analyze/` and are not part of the distributable Skill or final Git history. This report preserves their commands and aggregate literal results.
- The optional Comet scoped-text checker cannot traverse the deleted oversized baseline asset noted above. Independent secret/path scans and all current product files completed without that scanner.

# Conclusion

Pass. The confirmed pure Python dual-platform Skill contract, real production matrix, cleanup requirement, regression suite, and repository-boundary checks are satisfied with no unexplained implementation finding.
