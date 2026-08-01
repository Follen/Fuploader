# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-01639e6d41879ced6895dba0be645d9de19965c1c52bc42f65b5a89cd30706e7",
    "evidence_refs": [
      "publish/20260801-091500-dd-request-body-full-reaudit/read-matrix.json",
      "publish/20260801-091500-dd-request-body-full-reaudit/session-stop-output.json",
      "publish/20260801-091500-dd-request-body-full-reaudit/verification.json"
    ]
  },
  {
    "acceptance_id": "acceptance-39c9e7c288e74dc8ac3ad7d208ddb5565886a0b586b12339ba20212df8ac9142",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/dd_sidecar.py",
      "fupload/scripts/tests/test_dd_session.py"
    ]
  },
  {
    "acceptance_id": "acceptance-4184dd6606d9728a3570637bb92a132a07143380bf1b88e66d8a6e60984547e9",
    "evidence_refs": [
      "fupload/references/dd.md",
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_schema.py"
    ]
  },
  {
    "acceptance_id": "acceptance-690692902460983a121c71bc294c94ab3e1759f0183ce5702d880e154305683e",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd_sidecar.py",
      "fupload/scripts/tests/test_dd_session.py"
    ]
  },
  {
    "acceptance_id": "acceptance-8ce17ad817fa59a99dfbcb34f3107a0d088e858921bf8e677b9b8141fc11f4b2",
    "evidence_refs": [
      "README.md",
      "fupload/references/dd.md",
      "publish/20260801-091500-dd-request-body-full-reaudit/verification.json"
    ]
  },
  {
    "acceptance_id": "acceptance-9777d52d5648435ebd7616665e4576dc57d02d5460b80d23974fcbb2c8f6f769",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd_sidecar.py",
      "fupload/scripts/tests/test_dd_session.py",
      "publish/20260801-091500-dd-request-body-full-reaudit/verification.json"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

Change: `dd-request-body-full-reaudit`

The implementation and audit evidence are complete for the requested DD scope:

- field/action matrix and official evidence: `analyze/dd-request-body-full-reaudit-20260801.md`;
- request/response error capture code: `fupload/scripts/fupload_cli/dd_sidecar.py`;
- structured error propagation: `fupload/scripts/fupload_cli/dd.py`;
- regression coverage: `fupload/scripts/tests/test_dd_session.py`;
- live read/write/cleanup evidence: `publish/20260801-091500-dd-request-body-full-reaudit/verification.json`.

The live matrix used one serial session and one native login. Plugin, config, and WA
create/update/edit/delete all exited successfully, were read back, and were deleted
by the exact references created by that run. Exploration Season was excluded.

# Commands and results

| Command | Result |
|---|---|
| `python -m unittest discover -s fupload\\scripts\\tests -v` | 159 tests passed |
| `python -m compileall -q fupload\\scripts` | passed |
| `git diff --check` | passed; only line-ending conversion notices |
| `comet native check dd-request-body-full-reaudit` | passed; receipt `runtime/evidence/check-receipts/96dfa425bc3c235f7001e54cf56b69bcb53435234ac8c6b2f82c506578d6b0f4.json` |
| `dd session doctor` | DD installation signed/valid, GUI and broker not running, no login performed |
| controlled sidecar error fixtures | mutation, upload authorization, object PUT, and parsed HTTP status captured at `log_path` |
| live read matrix | all five non-Exploration game types and required dynamic dependencies read |
| live write matrix | plugin/config/WA create-update-edit-delete and cleanup passed in one session |

# Skipped checks

- No live write was made for Exploration Season.
- No existing user-owned WA2 record was changed; native WA2 behavior is covered by
  installed-client evidence and contract tests.
- `/addon/addon_versions` may be empty for private records and is therefore not a
  standalone write-success criterion.

# Spec consistency

- `schema.py` action allowlists match the plugin/config/WA create/update/edit/delete
  matrix in the canonical `dd-publishing` spec.
- `dd.py` re-GETs parent-dependent choices in the same session, rebuilds official
  wire objects, and performs resource-specific readback without replay.
- `dd_sidecar.py` preserves bounded sanitized request/response bodies, status,
  business code, validation hints, and log path while keeping signed URL and
  credential material out of CLI output and artifacts.
- `fupload/references/dd.md`, `fupload/SKILL.md`, and `README.md` describe the same
  one-session and dynamic-GET workflow.

# Known limitations and risks

- DD service/client behavior is versioned; this evidence is for the installed
  signed client and should be refreshed after a client upgrade.
- Read models can converge asynchronously. The bounded readback loop reports
  uncertainty and never resends a mutation.
- Exploration Season remains outside live-write coverage by explicit requirement.

# Conclusion

The change is ready for Comet Verify. The remaining HTTP-status diagnostic gap was
fixed without changing successful business payloads or retry semantics.
