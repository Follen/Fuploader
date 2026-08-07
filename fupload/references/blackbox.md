# Heybox Workshop

The blackbox provider reuses the signed-in Heybox desktop client's local login state. It never accepts credentials, cookies, tokens, signatures, or COS temporary credentials as input.

The npm installer manages Tencent's official COS SDK in a Fuploader-only Python venv. `fupload update` synchronizes it, the launcher repairs a missing or stale runtime before executing the Python CLI, and `fupload uninstall` removes it. No system-wide `pip install` is required.

## `blackbox plugin edit`

Edits existing module metadata and verifies the module detail readback. Input schema: `fupload.v1.blackbox.plugin.edit`.

Fields: `id`, `name`, `logo_url`, `category_ids`, `type`, `desc`, `official`, `official_url`, `core_folders`.

`id` is required. Omitted metadata fields preserve their current remote values. `category_ids` contains positive category IDs; `core_folders` is an array in the input and is sent as the platform's comma-separated value.

## `blackbox plugin update`

Uploads a local ZIP and creates one new plugin version. Input schema: `fupload.v1.blackbox.plugin.update`.

Fields: `module_id`, `name`, `type`, `game_versions`, `file`, `file_url`.

`module_id`, `name`, `type`, `game_versions`, and `file` are required. The provider uploads the ZIP through the official COS token flow, sends the server-normalized URL to the version upsert endpoint, and verifies `name`, `type`, `gameVersions`, and non-empty `fileUrlHeybox`.

## `blackbox plugin version-edit`

Edits one existing version. Input schema: `fupload.v1.blackbox.version.edit`.

Fields: `version_id`, `module_id`, `name`, `type`, `game_versions`, `file`, `file_url`.

`version_id`, `module_id`, `name`, `type`, and `game_versions` are required. Provide `file` to upload a replacement ZIP or `file_url` to reuse an already uploaded package; when both are omitted, the current server file URL is preserved.

## `blackbox plugin version-delete`

Soft-deletes one version and verifies `auditState=4` or absence after the platform's asynchronous processing. Input schema: `fupload.v1.blackbox.version.delete`.

Fields: `version_id`, `module_id`.

The provider may retry once when the platform temporarily returns a deleted version to an active audit state. Deleting the entire plugin module is not supported by the current client/web contract and is outside this command.
