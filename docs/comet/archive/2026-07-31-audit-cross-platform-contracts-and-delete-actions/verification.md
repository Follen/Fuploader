# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-02af1c9f2fb2b4b2462c59ca16d1cf9633c75325ee2adf07c786ed301e870d89",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/newbee.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_builders.py",
      "fupload/scripts/tests/test_schema.py",
      "publish/20260731-191228-cross-platform-contract-test/02-newbee-plugin-update.json"
    ]
  },
  {
    "acceptance_id": "acceptance-c488a5c173ded4e745630188aca2b7e6261f34eba4a393cdf48e8afe84182fbe",
    "evidence_refs": [
      "fupload/scripts/tests/test_builders.py",
      "fupload/scripts/tests/test_cli.py",
      "fupload/scripts/tests/test_schema.py",
      "fupload/scripts/tests/test_trust.py",
      "publish/20260731-191228-cross-platform-contract-test"
    ]
  },
  {
    "acceptance_id": "acceptance-cc2a9a0ae8ba44a1764fbbc18fad3822fd39743096489610850da2c47905f9aa",
    "evidence_refs": [
      "fupload/references/dd.md",
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_builders.py",
      "publish/20260731-191228-cross-platform-contract-test/13-dd-plugin-create.json",
      "publish/20260731-191228-cross-platform-contract-test/17-dd-config-create.json",
      "publish/20260731-191228-cross-platform-contract-test/21-dd-wa-create.json"
    ]
  },
  {
    "acceptance_id": "acceptance-d1ab89af4cb730f64028270c098b05c4893d9f66340d3877dcd6978286f93694",
    "evidence_refs": [
      "fupload/SKILL.md",
      "fupload/examples/dd-plugin-delete.json",
      "fupload/examples/newbee-plugin-delete.json",
      "fupload/scripts/fupload_cli/cli.py",
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/newbee.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_cli.py",
      "fupload/scripts/tests/test_schema.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `python -m unittest discover -s fupload\scripts\tests -v` -> `Ran 90 tests ... OK`; exit 0.
- `python -m compileall -q fupload\scripts` -> no diagnostics; exit 0.
- `git diff --check` -> no whitespace errors; exit 0. Git emitted only configured LF-to-CRLF checkout warnings.
- `comet native check audit-cross-platform-contracts-and-delete-actions --json` -> passed; 49 text files scanned, 311591 bytes, 0 issues; receipt `runtime/evidence/check-receipts/d63e1dd689545fb27d308501c2c5fcb2bc63a498703eab79c3690f1620cfcb85.json`; exit 0.
- Sensitive-keyword scan over `publish/**/*.json` -> no credential/token/cookie/client identifiers; 28 JSON files checked; exit 0.
- All 24 primary matrix JSON inputs and four post-fix DD configuration inputs passed their exact leaf command with `--dry-run`; each returned `schema_valid:true`; exit 0.
- NewBee live plugin: private create resolved ID `24462`; update version `1.0.0` bound build `12.1.0`; metadata edit matched; delete returned `present:false`; exit 0 after the readback helper fix.
- NewBee live configuration: private create resolved ID `58806`; content update and full metadata edit matched; delete returned `present:false`; exit 0 after role/media normalization fixes.
- NewBee live WA: private create resolved ID `9689`; update read back version `2.0.0` with content length/hash only; metadata edit matched; delete returned `present:false`; exit 0.
- DD live plugin: create resolved SN `d5552fd4e281487b9c62f61db90d0793`; author list showed version `1.1.0` and edited name while `detail_v2` remained stale under status `3`. Update/edit correctly returned `verification_required`; no write was retried. Delete returned `present:false`; exit 0.
- DD live configuration first run: create/update/edit/delete exercised all content groups. The run exposed a stale-detail metadata overwrite that reverted `Icons.inner_version` from 2 to 1; the fixture was deleted.
- DD live configuration post-fix run from `publish/20260731-195033-dd-config-retest/`: create resolved SN `96282722ebda4086805c886ccc563e18`; update set `Icons.inner_version=2`; immediate metadata edit retained inner version 2, updated description, all seven content groups, and retail UI state; delete and exact-name list returned zero; exit 0.
- DD live WA: create resolved SN `3e8381f195ba4ba5b1080075021965f4`; update read back version `2` and content length 48; metadata edit retained version/content/update description; delete returned `present:false`; exit 0.
- Final exact-name author-list checks for plugin/configuration/WA on both platforms returned zero remaining test objects; exit 0.

# Skipped checks

- Season of Discovery live mutation testing was skipped by explicit product decision. Retail, Titan Reforged, Mists of Pandaria, Burning Crusade, and Classic Era had current metadata and cloud-backup read checks.
- DD plugin moderation did not expose the new version through `addon_versions` or updated metadata through `detail_v2` during the test window. The author list proved the submitted version/name, while the provider intentionally retained `verification_required` and did not retry.

# Spec consistency

- NewBee build values are strings from live metadata, not parent branch IDs; upload readback requires all requested version bindings.
- Dynamic NewBee origins/plans/time ranges and DD builds/categories/channels/associations/lifetimes are endpoint-specific and fail closed when empty or malformed.
- DD non-create writes compare detail and author-list timestamps before POST. Configuration metadata edits verify preserved update description, seven content groups, inner versions, and retail UI state.
- Both platforms expose six single-record delete leaves with literal `DELETE`, pre-read target identity, one delete request, and post-delete absence verification.
- Skill invocation is explicit, Python is the only implementation, publish inputs are project-local and tracked, and exploration reports remain ignored under `analyze/`.

# Known limitations and risks

- DD's author list and detail/version read models can converge at different times under moderation. The CLI fails closed with `verification_required`; callers must read again later instead of resending writes.
- DD native requests occasionally returned read timeouts. Errors now preserve the endpoint and mark POST/upload failures as uncertain writes; preflight GET failures remain distinguishable.
- Real tests used private/free/no-channel/no-association settings to avoid public review and unrelated room effects. Public, paid, channel-linked, associated, and VIP combinations are covered by schema/provider tests and live option reads, not by destructive production mutation.

# Conclusion

Pass. All four acceptance examples have direct project evidence, the implementation scope is complete, 90 tests pass, the post-fix DD configuration chain passed against the live platform, and no test fixture remains on either platform.
