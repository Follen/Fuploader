# Blackbox Client Session Compatibility

## Requirement: load the current Heybox desktop session
The provider MUST prefer the official desktop profile at `%APPDATA%/heybox-pc-launcher/config.json`. It MUST locate the account id, encrypted `user_pkey`, and `x_xhh_tokenid` without logging their values. The encrypted pkey MUST be decrypted with the client-compatible AES-256-CBC format and the configured key. If the official config is absent or incomplete, the provider MAY fall back to the Chromium `Network/Cookies` database.

## Requirement: construct current client requests
Requests MUST include the current desktop identity fields (`x_client_type=pc`, `x_os_type`, `x_app=heybox_pc`, `version`, `exe_version`, `os_version`, `device_id`, and `heybox_id`) when available, plus `_time`, `_chat_time`, `nonce`, and `hkey`. The hkey input timestamp MUST match the 1.14.1 client implementation. Authentication MUST send the current token header and Cookie values without exposing them in errors or artifacts.

## Requirement: preserve Workshop management operations
The provider MUST continue to support plugin list, detail, version list, module metadata update, version create/update, and version delete. Omitted metadata fields MUST be preserved from a detail read. Whole-module deletion is out of scope.

## Requirement: upload plugin archives with the current COS protocol
For the current client protocol, archive upload MUST support the sequence `info/v2 -> token/v2 -> COS object upload -> callback/v2`; multipart uploads MAY use heartbeat. The implementation MUST retain the old `/wow/cos/upload/token/` fallback only when the current protocol is unavailable and MUST return a verified URL and checksum.

## Requirement: verify and rollback real mutations
Every real version mutation MUST use a unique marker, poll the version list for readback, retry deletion when the audit state remains active, and restore the baseline module fields and active version set. Verification output MUST include exact commands, redacted inputs, literal statuses, exit codes, and runnable rollback.

## Requirement: preserve analysis evidence
The change MUST add or update redacted artifacts under `analyze/` covering client version/session storage, request signing, web capture routes, COS field shapes, verification results, source hashes, and known evidence gaps. Raw credentials and raw request bodies MUST NOT be added.
