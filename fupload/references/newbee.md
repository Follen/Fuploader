# NewBeeBox field and workflow reference

## Session and dynamic reads

Use `newbee session doctor`. Authentication is taken from the Windows Known Folder Roaming AppData path `NewBeeBox/auth-store`. Creator, auth, metadata, next-API, and upload origins are fixed official HTTPS values; environment variables cannot replace them or the credential directory. Never request a token.

- Plugin choices: `plugin categories`, `plugin game-versions`.
- Plugin state: `plugin list|get|versions`, `plugin changelog list|get`.
- Configuration choices: `config backups`, then `config backup-get --id <cloud_id>`.
- Configuration state: `config list|get`.
- WA choices: `wa categories --game-version-id`, `wa attachment-paths`.
- WA state: `wa list|get`, `wa changelog latest|list`, `wa co-author search|list`, `wa reference search|list`.

Game-version IDs distinguish retail, classic, Titan Reforged, and any later server builds. Always show the live list; do not hardcode labels or IDs.

## Plugin

`plugin create` fields:

| Field | Requirement and meaning |
| --- | --- |
| `name` | Required name. |
| `mod_categories` | Required array selected from live categories. |
| `content_origin` | Required origin selection. |
| `content_format` | Required description format. |
| `intro`, `description` | Required short and full descriptions. |
| `logo` or `logo_file` | One required; remote reference or local upload. |
| `screenshots`, `screenshot_files` | Optional existing references and local additions. |
| `public` | Required visibility choice; new records may remain private. |
| `submit_for_review` | Required as `true` when `public=true`. |
| `subscribe_plan_level`, `link_to_channel` | Optional plan/channel choices. |

`plugin update` publishes one immutable version. Required: `mod_id`, `version`, `game_version_list`, `file`. Optional: `changelog`, `link_to_channel`. Packages are `.zip`, `.rar`, or `.7z`, at most 300 MB. Existing versions are rejected before upload.

`plugin edit` requires `id`; every create metadata field is optional and presence-aware. `public=true` requires `submit_for_review=true` and an existing version. Explicit empty descriptions/screenshots clear only where the platform accepts them.

Version logs use `plugin changelog edit`: `file_id` and present `changelog`; empty string or null explicitly clears the log.

Wire endpoints: `/creator/wow/mod/create|edit`, `/creator/wow/mod_file/upload_mod_file`, and changelog endpoints. Visibility wire values are private `share_state=0`, public/review `share_state=1`.

## Configuration share

`config create` fields:

| Group | Fields |
| --- | --- |
| Backup content | Required `cloud_id`, `linked_mods`, `ignored_unknown_mods`, `ignored_materials`, `ignored_fronts`, `roleid`. |
| Metadata | Required `title`, `content`, `content_format`, `content_origin`; optional `intro`. |
| Media | At least one of `picture_urls` or `picture_files`. |
| Visibility | Required `public`; `submit_for_review=true` when public. |
| Commercial/channel | Optional `subscribe_plan_level`, `price`, `time_range`, `link_to_channel`. |

Each `linked_mods` object supports `mod_id`, `mod_name`, `mod_file_id`, `mod_version`, `display_name`, and `update_type`. Choose these from `backup-get`; do not guess missing file/version values.

`config update` requires `id` and only changes backup content: `cloud_id`, `linked_mods`, the three ignored arrays, and `roleid`. When `cloud_id` is present, all other backup selections are required and must come from that backup.

`config edit` requires `id` and only changes metadata/media/visibility/commercial/channel fields. It cannot change `cloud_id`. Both update and edit GET the current detail and call `/creator/wow/share_config/update` with a complete allowlisted payload. Visibility wire values are `sharing=0/1`.

## WA/string

`wa create` metadata fields: required `game_version_id`, `name`, nonempty `description`, `content_format`, `category_id_list`, `content_origin`, `public`; optional `intro`, `images`, `image_files`, `subscribe_plan_level`, `price`, `time_range`, `link_to_channel`, `attachments`. One of `thumbnail` or `thumbnail_file` is required. `submit_for_review=true` is required when public.

First-version fields are required `wa_str`, `wa_log`, and `string_mode` (`single` or `collection`); `wa_str_titles` is required for collection mode and must follow string order.

Each attachment object has exactly `name`, `install_type`, `install_path`, `value`, `is_compressed`, and optional `timestamp`. Select install values from `attachment-paths`. `value` is the uploaded attachment index code. `wa media upload` accepts `file`, `kind`, `install_type`, and `install_path`; with `kind=attachment` it follows the production uploadserver v3 prepare, object PUT with callback, and index readback chain, then returns an `attachment` object. Include install values if you want that object to be directly pasteable into `attachments[]`. Use `kind=image` for Creator image media.

`wa update` requires `id`, `wa_str`, `wa_log`; optional `version`, `wa_str_titles`, `link_to_channel`. The provider GETs the next version when omitted and calls `update_wa_str` without metadata changes.

`wa edit` requires `id`; all metadata fields above are optional/presence-aware and it never includes string-version fields. Visibility wire values are private `share_state=2`, public/review `share_state=1`.

Attached actions are independent: `wa media upload`, `wa changelog edit`, `wa co-author set`, `wa reference set`, and `wa share-code set`. WA changelog edit requires log `id` and `wa_log`; optional `wa_id` enables immediate list readback after the edit. Co-author replacement requires `content_id` and `co_authors`; each item is `{user_id,share_percent}` and the total is at most `1`. Reference replacement requires `source_id` and `references`; each item is `{type,id}`. Share-code refresh requires `module_id`. Empty arrays explicitly clear the respective complete relationship.
