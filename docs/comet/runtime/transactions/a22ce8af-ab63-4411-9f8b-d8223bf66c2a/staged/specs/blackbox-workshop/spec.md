# Blackbox Workshop capability

## Command surface

Fuploader exposes the `blackbox plugin` resource with read leaves `list`, `get`, and `versions`, plus write leaves `edit`, `update`, `version-edit`, and `version-delete`. Every write accepts one versioned JSON document through `--input` and supports local `--dry-run` validation. Module-level deletion is not exposed.

## Authentication and transport

The provider reads the signed-in Heybox desktop profile from the current Windows user's roaming application data. It accepts no caller-supplied cookie, token, signature, profile path, API endpoint, or COS credential. Workshop requests use the fixed official HTTPS API origin, the client identity fields available in the profile, and the client-compatible request signature. Outputs and errors redact credential and signature fields.

ZIP upload uses the official `cos-python-sdk-v5` package and temporary credentials returned by the Workshop COS token endpoint. The provider uploads the existing archive as read-only input, returns its byte count and SHA-256 internally, and submits the resulting object URL to the version API. A missing COS SDK is reported as an environment error with the installation command.

## Read behavior

`plugin list` returns the current account's module rows and a total count. `plugin get` returns one module and its versions. `plugin versions` returns the same version projection for one module ID. Read responses retain business fields and redact credential-like fields recursively.

## Module metadata edit

The editable module fields are `name`, `logo_url`, `category_ids`, `type`, `desc`, `official`, `official_url`, and `core_folders`, with immutable positive `id`. The provider reads the current module, overlays only fields present in the JSON document, converts `core_folders` to the platform comma-separated wire representation, and sends the complete module form. It then reads the module again and verifies every caller-specified field. A mismatch is a verification-required failure.

## Version create and edit

Version create requires `module_id`, `name`, `type`, `game_versions`, and a local ZIP `file`. Version edit also requires `version_id`; it may upload a replacement `file`, reuse an explicit `file_url`, or preserve the current server file URL when both are omitted. The provider sends the complete version form, polls the version list until `name`, `type`, and `gameVersions` match, and requires a non-empty authoritative `fileUrlHeybox` in the readback. It never blindly retries an ambiguous upsert.

## Version deletion

Version deletion requires `module_id` and `version_id`. It invokes the version-delete endpoint and polls until the row is absent or reports `auditState=4`. After the initial delete settles, the provider retries once only when the same row has returned to a non-deleted audit state, then verifies the final readback. It never deletes the module itself.

## Validation and compatibility

All commands use `fupload.output.v1`. Unknown JSON fields, invalid IDs, invalid version types, empty required version arrays, and missing or invalid local archives fail before authentication or network writes during `--dry-run`. Existing NewBeeBox, DD, and CurseForge routes retain their current schemas and behavior. Automated tests cover routing, schema state matrices, provider mutations, and package manifest consistency.
