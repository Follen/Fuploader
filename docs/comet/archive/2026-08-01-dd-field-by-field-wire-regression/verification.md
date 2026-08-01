# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-183629b6fc7ae465e26cd5d559a60ab40f21b9eca7eb514138c8d5df8d54b7d8",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-1b64f08a6f890ea4a943843e1eb5e7de236c7191f9bbbbd15ca2a9262c47cd12",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-1b8bdef8c73b83b1a99799549954c21e7d1bd8441765175d240698ac8b77ed0c",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-1e1d4bfc95f5a82b1b47a949a15b525635a3added74b67ed3df4198239a9d40f",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-612ab103ca1629bf45a64e07d7e2fba8765fb57e6049ff293133d1db4ff2915a",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-6713a43b896becea2b106cbf0734e75f2ff9ae3dab249aec6ee419cdaf14174e",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-78c317d8d9a57ba0804291765bccaed600dbbce83de9d7ca932e44ad4b862c00",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_session.py"
    ]
  },
  {
    "acceptance_id": "acceptance-84c3b31607167bed5753ccbf2f7dde7d76da057cad9abc5e78bc80ab98d632e1",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_session.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-a978e83f4d72c2d725396a4964ef82cc7b652b0ba3bbd59192666bfd45dee538",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-d9b5713c68f879d1f92b57588910fc5acad0c49b1d99ae7c7902a04e8930ac02",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/fupload_cli/schema.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-ed6b9abb8a0ec4d9b53f159ed5203ad187a843a4a5e33493ac2bff977b02e3e0",
    "evidence_refs": [
      "README.md",
      "fupload/scripts/tests/generate_dd_wire_matrix_report.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f0972f844d8ed7b4958d93ef815e8c5515b194151889003c3adb26231b72eb34",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_session.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f342e95983e0298f9c393c490cf94d71fd6dfdbd54b306b54aab4e60a81d48d6",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f8ae38a7ef39e8a74f54a4566904e46f851e43d05b2fcffce173c8cb7837936c",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_dd_wire_matrix.py"
    ]
  },
  {
    "acceptance_id": "acceptance-fdb673edc9b8a2435bb7e20f0b16a933b25801e16e4d935c76478c29db771726",
    "evidence_refs": [
      "fupload/scripts/fupload_cli/dd.py",
      "fupload/scripts/tests/test_builders.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

Change: `dd-field-by-field-wire-regression`

# Result

PASS. The executable DD catalog covers 195 schema fields across plugin, config,
and WA create/update/edit/delete. The generated matrix contains 1246 field/state
and targeted cases with zero schema/catalog gaps.

The matrix found and fixed three production differences: missing local image
files now fail at their indexed JSON path; config update markers work when the
unchanged selection array is omitted; and stale update markers fail before any
upload or mutation.

# Commands and results

| Command | Exit | Result |
|---|---:|---|
| `python -m unittest discover -s fupload\scripts\tests -v` | 0 | `Ran 172 tests in 10.720s`; `OK` |
| `python fupload\scripts\tests\generate_dd_wire_matrix_report.py > analyze\dd-field-by-field-wire-regression-20260801.md` | 0 | dedicated matrix: `Ran 12 tests in 0.217s`; `OK`; report generated |
| `python -m compileall -q fupload\scripts` | 0 | no output |
| `git diff --check` | 0 | no whitespace errors; line-ending conversion notices only |
| `comet native check dd-field-by-field-wire-regression` | 0 | passed; receipt `runtime/evidence/check-receipts/235d865119097910bbd958ca6a58ea6f6a511cb7b886cf04bae8e3f6f5d9b254.json` |
| credential-pattern scan of 9 public implementation/spec files | 0 | `CredentialMatches=0` |

# Matrix evidence

- The generated report has 1282 lines, 195 schema action fields, 1246 cases,
  and zero gaps.
- Normal, alternate, omitted, null, invalid type, false, zero, empty, boundary,
  invalid enum, stale child, and stale selector states are represented where
  applicable.
- The capture session JSON-round-trips final request bodies and distinguishes
  dependency reads, native parsing, upload authorization, object PUT, mutation,
  and readback.
- HTTP 400/401/403/404/422/500 fixtures passed. Explicit 4xx rejection remains
  deterministic; 5xx and incomplete mutation transport remain uncertain and
  never trigger an automatic replay.

# Live evidence

The isolated non-Exploration live run used one DD login and one serial task
session. All 12 plugin/config/WA create, update, edit, and delete steps exited 0.
The exact temporary plugin, config, and WA references were all absent after
cleanup; session stop exited 0. A subsequent read-only session status returned
`running=false` and `login_performed=false`.

The existing dynamic read matrix covered five available non-Exploration game
types, including their live build/category dependencies and available backup
details. The account-side records remain local-only and are excluded from the
public commit.

# Skipped checks

- Exploration Season live writes were excluded by requirement.
- A real account object was not mutated once per field. The exhaustive per-field
  contract is deterministic; live writes validate the representative end-to-end
  resource/action chain.
- DD behavior is client-versioned. The matrix and read smoke must be rerun after
  an official client or web contract change.

# Spec consistency

The implementation matches the approved DD field-by-field wire contract. All 15
Runtime acceptance examples have project-relative evidence references, and no
acceptance item is skipped.

# Known limitations and risks

Official DD client and web contracts can change independently of this repository;
the generated matrix proves the captured contract and must be refreshed on drift.

# Conclusion

PASS.
