# Outcome

Add a first-class Heybox Workshop (黑盒工坊) plugin management path to Fuploader. The user will be able to list and inspect modules, edit module metadata, create or edit a module version with a local plugin archive, and delete a module version through schema-validated JSON commands. The provider will reuse the installed Heybox desktop client's login state, use the official Workshop COS flow, and verify every server-side mutation.

# Scope

- Add a `blackbox` platform provider and plugin read/write leaves to the existing Fuploader CLI: `list`, `get`, `edit`, `update`, `version-edit`, and `version-delete`.
- Read the existing module before writing and require stable module/version IDs plus the fields applicable to the chosen operation.
- Support module metadata fields proven by the live test: `name`, `logoUrl`, `categoryIds`, `type`, `desc`, `official`, `officialUrl`, and `coreFolders`.
- Build the real archive upload request, create or edit the Workshop version, preserve the server-normalized file URL, and poll `module_version/list` until the mutation is visible with matching fields.
- Reuse the Windows Heybox client profile under the user's roaming application data; never accept or print cookies, tokens, signatures, or COS temporary credentials.
- Follow the repository's JSON output, dry-run, publish-record, and post-write verification conventions.

# Non-goals

- Module-level deletion is explicitly out of scope: the captured developer frontend exposes no module-delete endpoint. The ordinary `/workshop/home/mine/delete` endpoint only removes a user's history item (`type` + `item_id`) and is not a plugin-owner deletion contract.
- No browser automation or reverse-engineering capture in the product command.
- No new plugin/module creation or public-review workflow beyond the existing module update and version upsert contracts.
- No changes to the user's real plugin source directory or its existing ZIP.

# Acceptance examples

- `fupload blackbox plugin update --help` exposes the stable JSON schema and `--dry-run`.
- Dry-run validates a real TapTool archive and rejects missing/invalid module ID, version, game version, type, or file without authentication or network writes.
- A live run with the client login state uploads the archive, creates one test version, polls it back, and reports the canonical server file URL without leaking credentials.
- A real readback confirms the created version's name, type, game versions, module ID, and non-empty file URL; an interrupted or ambiguous write is reported as verification-required rather than retried blindly.
- Existing NewBeeBox, DD, and CurseForge commands retain their current behavior and tests.

# Constraints and invariants

- Official HTTPS Workshop API and COS origins are fixed in code; endpoint or credential-directory overrides are rejected.
- All writes are serial and use `GET -> validate -> upload -> upsert -> readback`.
- JSON input and output are stable, secret-free, and compatible with the existing `fupload.output.v1` contract.
- `moduleId` and `versionId` are identity keys, not mutable business fields; module edits preserve `id`, version edits preserve `versionId`, and version deletion is soft-deletion with explicit readback.
- Product tests use a copy/archive under `publish/` or an ignored test directory; `D:\Code\TAP Tool\TapTool` remains untouched.

# Decisions

- Use the platform name `blackbox` and the command shape `blackbox plugin <action>`, matching the existing platform/resource/action tree.
- Use the existing JSON `--input` plus optional `--dry-run` convention instead of adding positional flags.
- Use the Heybox desktop client's local login state, not browser cookies or manually supplied credentials.
- Treat the server's `fileUrlHeybox` as authoritative after COS upload; do not require it to equal the temporary COS object URL.

# Open questions

- Module-level delete is not implemented; version deletion is the supported delete operation for this change.

# Verification expectations

- Run the existing Node/Python test suites and focused blackbox provider tests.
- Run `--dry-run` against a real TapTool ZIP.
- Run live TapTool tests through the client login state for metadata edit, version create/edit/delete, verify every submitted field, and clean up test versions with explicit readback records.
- Record commands, exit statuses, redacted responses, package hashes, and rollback/cleanup evidence under the Native verification artifacts.
