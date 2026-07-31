# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0e747c2581bbae493fab8b9d95d2edc158997dc7fa05d8cfb067e9539c935bdc",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/trust.py",
      "fupload/scripts/tests/test_builders.py",
      "fupload/scripts/tests/test_trust.py"
    ]
  },
  {
    "acceptance_id": "acceptance-36cd01d6dfb53ff8f67a9b71311c6200a971e3426eae6832ea73dc0d2dee5d37",
    "evidence_refs": [
      "fupload/references/dd.md",
      "fupload/references/newbee.md",
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/newbee.py"
    ]
  },
  {
    "acceptance_id": "acceptance-44c1d4e03a67dbe0f9a9871ad62489d2711c26e40993e809e222c8724d9030fc",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/newbee_auth.py",
      "fupload/scripts/fupload_cli/trust.py",
      "fupload/scripts/tests/test_trust.py"
    ]
  },
  {
    "acceptance_id": "acceptance-55da2a03da7e2031b7667723a8f70cd1397115a13040b633e70dbdd30eeb0d27",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/transport.py",
      "fupload/scripts/fupload_cli/trust.py",
      "fupload/scripts/tests/test_trust.py"
    ]
  },
  {
    "acceptance_id": "acceptance-bc10f0ffed545a4bd5f756c236543e3892b8932a7cc540382a590a8bf4328c39",
    "evidence_refs": [
      "fupload/scripts/tests/test_builders.py",
      "fupload/scripts/tests/test_cli.py",
      "fupload/scripts/tests/test_schema.py",
      "fupload/scripts/tests/test_trust.py"
    ]
  },
  {
    "acceptance_id": "acceptance-c23a16850fe085949e4d17c4c51c7fbd808584eba1c6e8e752b18e5556852119",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/newbee.py",
      "fupload/scripts/fupload_cli/trust.py",
      "fupload/scripts/tests/test_trust.py"
    ]
  },
  {
    "acceptance_id": "acceptance-d8e1e58d4502e7bde58471667ffc25975144defd417d53991c8cb11288769f80",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/newbee.py",
      "fupload/scripts/fupload_cli/newbee_auth.py",
      "fupload/scripts/fupload_cli/trust.py",
      "fupload/scripts/tests/test_trust.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `python -m unittest discover -s fupload\scripts\tests` -> `Ran 68 tests ... OK`; exit 0.
- `python -m unittest tests.test_cli.CLITests.test_all_bundled_examples_pass_dry_run` from `fupload/scripts` -> the six bundled NewBee/DD examples passed dry-run; exit 0.
- `python -m compileall -q fupload\scripts` -> no diagnostics; exit 0.
- `git diff --check` -> no whitespace errors; exit 0. Git emitted only configured LF-to-CRLF checkout warnings.
- Production override scan for `FUPLOAD_NEWBEE_*`, `FUPLOAD_DD_DIR`, `NETEASE_DD_DIR`, and `APPDATA` reads in provider code -> `no production environment override reads`; exit 0. The only remaining `NETEASE_DD_DIR` use is the parent-to-validated-sidecar internal handoff.
- `python fupload\scripts\fupload.py newbee session doctor` -> authenticated from Windows Known Folder auth-store, reported five fixed official HTTPS origins and `trusted=true`; exit 0.
- `python fupload\scripts\fupload.py newbee plugin game-versions` -> six live builds, including retail, Titan Reforged, Mists of Pandaria, Burning Crusade, classic, and Season of Discovery; exit 0.
- `python fupload\scripts\fupload.py dd session doctor` -> authenticated, automatically selected DD `100128`, verified Authenticode `Valid` and publisher `NetEase (Hangzhou) Network Co., Ltd`, and reported Known Folder sidecar state; exit 0.
- `python fupload\scripts\fupload.py dd options game-types` -> five live builds: retail, Titan Reforged, Mists of Pandaria, Burning Crusade, and classic; exit 0.
- `comet native check harden-auth-trust-boundaries` -> passed; receipt `runtime/evidence/check-receipts/e842a36bfd418e22dffe6214c1b842ad0610dd852b365ef41a939f80580ea4c9.json`; exit 0.

# Security review

- NewBee production endpoint and auth-directory environment overrides are removed. Host, scheme, and effective port are checked before requests; redirects are limited to the same HTTPS origin.
- Windows Known Folder API determines Roaming/Local AppData. Credential and state subpaths reject symlink/reparse traversal and path escape.
- DD discovery no longer prioritizes environment-supplied executable paths. Every structurally valid candidate is checked with Windows Authenticode, and the parsed signer `O=` organization must exactly match the maintained official publisher set.
- DD signature output is reduced to status and publisher organization; certificate serial and full subject are not returned.
- Review found and fixed three implementation defects before final verification: the generic transport fallback used the wrong opener API, the Windows reparse attribute constant was incorrect, and the initial DD publisher check used a subject substring instead of exact parsed organization identity.

# Skipped checks

- No remote create/update/edit/delete command was run. This change modifies authentication trust boundaries, not resource payloads; read-only doctor and live build discovery provide production-chain evidence without recreating the previously cleaned test objects.
- Existing create/update/edit schemas, 64 CLI leaves, business payload builders, and six examples remain covered by the full regression suite.

# Spec consistency

- The implementation matches the four proposed full target specs: fixed NewBee origins, Windows Known Folder state, same-origin redirect enforcement, DD official publisher verification, and redacted doctor diagnostics are all present in code, Skill/reference documentation, and tests.
- No public CLI leaf, write schema, business field, payload builder, review behavior, or delete boundary changed.

# Known limitations and risks

- The maintained DD publisher allowlist currently contains the verified organization `NetEase (Hangzhou) Network Co., Ltd`. A future official client signed by a different NetEase legal entity will fail closed until that organization is reviewed and added.
- Authenticode verification uses the absolute Windows PowerShell system executable and the built-in `Microsoft.PowerShell.Security` module with a sanitized module path. A damaged Windows security module causes DD discovery to fail closed.
- Official NewBee domain changes require a reviewed code update. Runtime endpoint override is intentionally unavailable.
- The remote write matrix was not repeated because the change does not modify payload behavior and repeating it would recreate objects already deleted after the previous full production verification.

# Conclusion

Pass. All seven acceptance examples have direct project evidence, complete implementation scope, passing regression and live read-only checks, and no remaining unexplained finding.
