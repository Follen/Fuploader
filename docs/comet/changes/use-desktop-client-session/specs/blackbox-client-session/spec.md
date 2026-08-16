# Blackbox Managed Web Session Compatibility

## Requirement: use only a Fuploader-managed web session

The Blackbox provider MUST use a Fuploader-managed Chromium persistent profile created inside the product state directory as its only authentication source. It MUST NOT load, require, or inspect the Heybox desktop client's `config.json`, account state, Cookie storage, installation, or running process. The desktop client being absent, stopped, or signed out MUST NOT prevent Blackbox from opening or reusing its managed web session.

The provider MUST never open or import Chrome, Edge, Electron, another Playwright profile, or system browser Cookie databases. The profile directory MUST be selected internally and MUST NOT be supplied through a command document or ordinary configuration. Cookie values and storage state MUST remain inside the persistent BrowserContext and MUST NOT be exported into an independent request context, state file, or command output.

The web-session state machine MUST have explicit `headless_probe`, `headed_login`, `ready`, `expired`, and `failed` states. It MUST begin with a headless probe of the fixed Workshop entry URL and a read-only module-list protocol request. On `login`, `relogin`, expired storage, or an unusable profile, it MUST transition to `headed_login`, open the same persistent profile in a visible Chromium window, and wait for the Workshop route plus a successful read-only module-list response. It MUST persist only non-sensitive state metadata; cookies, storage values, web tokens, and signed URLs remain inside the browser profile and process memory.

After headed login succeeds, subsequent calls MUST return to headless mode and reuse the same profile. A web session expiry during a read or before a mutation MUST trigger one headed re-login and then retry the read-only operation; an uncertain mutation MUST return `verification_required` and MUST NOT be replayed automatically.

## Requirement: reproduce the current web request contract

Workshop requests MUST use a fixed allowlisted protocol route through the managed Playwright BrowserContext request object so HttpOnly browser cookies remain attached without being exported. The route MUST generate the web signer and identity fields observed from the Workshop page, MUST reject arbitrary absolute URLs and caller-supplied headers or credentials, and MUST return redacted status/error data to the CLI. The protocol implementation MUST support GET reads and URL-encoded POST mutation forms without exposing the browser page or request body as command output.

The signer MUST match fixed regression vectors captured from successful web requests and MUST vary correctly across different paths, timestamps, and nonces. Authentication cookies MUST remain in the BrowserContext Cookie jar; only the query fields and request headers demonstrated by the current web client MAY be sent.

Callers MUST NOT be able to supply a profile path, cookie, token, pkey, signature, API origin, or temporary upload credential through a Blackbox command document or ordinary configuration. Errors and output MUST recursively redact credentials, signatures, nonce values, device identifiers, and signed upload parameters.

## Requirement: preserve Workshop plugin management

The provider MUST continue to support plugin list, plugin detail, version list, complete module metadata update with omitted-field preservation, version creation, version edit, archive replacement, and individual version deletion. It MUST NOT expose or invoke whole-module deletion.

Module edits MUST read the current module, overlay only caller-specified allowed fields, submit the complete current-client form, and compare each requested field with a fresh detail read. Version creation and edit MUST submit the current-client field set, poll GET-only readback, verify name, type, game-version bindings, and an authoritative non-empty archive URL, and MUST NOT blindly replay an ambiguous mutation.

Version deletion MUST poll until the row is absent or has the deleted audit state. After the first delete settles, it MAY retry the same delete exactly once only if the same version becomes active again, then MUST perform final GET-only verification.

## Requirement: upload plugin archives through the supported client flow

ZIP upload MUST use the verified web creator flow, including the allowlisted Workshop upload-token route and constrained COS object upload. It MUST NOT depend on desktop-account API endpoints. Temporary COS credentials and signed URLs MUST remain in memory and MUST NOT be written to plans, logs, analysis, or command output. The existing archive is read-only input; the provider MUST calculate byte count and SHA-256 and return only non-sensitive verification metadata.

If more than one verified upload flow remains supported, fallback is allowed only after a definite pre-mutation unavailability response. A timeout or uncertain object upload/callback MUST be reported as verification-required and MUST NOT cause an automatic second upload.

## Requirement: verify the real TapTool workflow and restore baseline

Real verification MUST use the Fuploader-managed web creator session to select the TapTool plugin from the current account. It MUST record a redacted baseline for module fields and active versions, then exercise read list/detail/versions, allowed module-field edits, test-version creation with a ZIP from `D:/Code/TAP Tool`, version-field edits, archive replacement, and individual version deletion. Whole-module deletion MUST NOT run.

Every test mutation MUST use a unique marker and immediate GET-only readback. The final rollback MUST restore all changed module fields and remove or mark deleted every test version so the active module fields and version set match the baseline. Verification evidence MUST include exact commands, redacted inputs, literal statuses, exit codes, baseline/modified comparisons, and a runnable rollback procedure.

## Requirement: preserve auditable analysis without credentials

The change MUST update artifacts under `analyze/blackbox/client-session-20260816/` with installed client version and hashes, session-field provenance, bytecode/decompilation findings, signer vectors, endpoint and field matrices, upload-flow evidence, real verification results, and unresolved evidence gaps. Raw cookies, pkeys, tokens, device ids, signatures, nonces, signed URLs, request bodies containing private content, and temporary credentials MUST NOT be committed.

Analysis MUST also record the managed-profile state-machine transitions, Playwright/Chromium versions, venv dependency hashes, protocol allowlist, login/readiness probes, and redacted expiry/re-login results. It MUST NOT record the persistent profile contents or storage state.

## Requirement: release the repaired provider consistently

Automated verification MUST cover the absence of desktop/browser database access, managed-profile selection, headed/headless transitions, web request identity and signer vectors, recursive redaction, Workshop read requests, module edits, version create/edit/delete, and ZIP upload behavior. Existing non-Blackbox provider behavior MUST remain unchanged.

Before Native archive, release preparation MUST advance all package version carriers to the same next SemVer, rebuild the distribution manifest, pass package and installation checks, verify the target tag is unoccupied, and confirm the tag publication workflow is available. The operational release then occurs after Native archive: merge into `main`, create the tag from merged `main`, wait for tag CI, and confirm npm `latest` equals the released version.
