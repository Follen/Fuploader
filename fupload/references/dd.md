# NetEase DD field and workflow reference

## Task session

Run `dd session doctor` first. Doctor only discovers the installation, verifies the Authenticode publisher, reports official DD processes and reads local broker state; it does not login. When `gui_running=true`, explain that the official DD GUI must close and obtain explicit user consent. Only then run `dd session start --confirm-close-gui`. When `gui_running=false`, run `dd session start` without the confirmation flag.

`start` closes only identity- and signature-verified official GUI processes, starts one task broker and returns an opaque `session_id`. Pass that value through `--session` to every DD read and write. All operations are serialized through one native login. Run `dd session status --session <id>` for a local status check and always run `dd session stop --session <id>` in `finally`; successful stop reports `cleanup_complete=true`. The ten-minute idle timeout is only a crash fallback.

Do not request or expose token, Cookie, JWT, credential database, signed URL, `clientNo`, raw WA content, or raw backup objects. The device state remains under Windows Known Folder Roaming AppData at `CCVoiceHub/Fupload/sidecar-device.json`.

## GET before one final JSON

DD GUI fields are not a flat form. Resolve these dependencies before generating the write JSON:

- `game_type` -> `game_versions`, `associated_acts`, WA `category_ids`;
- `primary_category_id` -> `second_category_ids`;
- `scope` -> `share_code_life_type`, anchor-VIP availability, `sync_room`;
- outer free/paid state -> `need_buy`, `need_anchor_vip` -> `price_fen`, `buy_life_type`, `vip_levels`;
- `jump_room` -> `room_id` -> `channel_id` and `channel_type`;
- `backup_sn` -> backup detail -> WTF account/server/role -> account-scoped `known_wa_ids` and `unknown_wa_ids`;
- retail backup -> `retail_ui_config` selectors;
- `with_file` -> WA `file` and `file_install_path`.

Choose a parent, GET and display only that parent's child choices, then continue. Changing a parent invalidates all descendants. Generate one final JSON only after the graph closes. Store parent fields and stable IDs/opaque selectors, never copied backend objects or display names.

The Python provider repeats every live GET in the same session before any upload or mutation. A missing, duplicate, or cross-parent selection fails at its exact JSON path with `verification_required=false`. DD detail is authoritative for an existing object's form and ownership; author-list timestamps are not comparable freshness gates.

Author-owned plugin/config/WA lists and association candidates traverse the real DD pagination contract instead of assuming the first 100 rows contain every selected SN. Repeated pages or the bounded page limit are platform-data failures and stop the write before upload.

## Shared fields

All three create/edit form models use `scope`, `share_code_life_type`, `need_buy`, `price_fen`, `buy_life_type`, `jump_room`, `room_id`, `channel_id`, `channel_type`, `sync_room`, `creation_statement`, `with_associate`, `associated_acts`, `need_anchor_vip`, and `vip_levels`.

- `scope` is `public` or `private`. Private requires `share_code_life_type`, clears anchor VIP and room sync. Plugin/WA public force `share_code_life_type=forever`; config public omits it.
- `need_buy=true` requires `buy_life_type`; `price_fen` may be `0` or `10..20000` fen because the official submit validation explicitly accepts zero. A free create resolves to zero, while an existing paid form may retain a hidden historical price when `need_buy` is turned off but the outer paid mode remains active through anchor VIP.
- The outer free/paid selector is locked after an SN exists. It is derived from `need_buy || need_anchor_vip` and is not a wire field. Existing paid content may still adjust payment methods and their price/lifetime/VIP children while remaining paid.
- `jump_room=true` requires `room_id`. `channel_id` and `channel_type` are both empty for a room-only link or both present for one live child channel.
- `with_associate=true` requires nonempty `associated_acts`; each item is exactly `{sn,act_type}` with `act_type` `addon`, `share`, or `wa`.
- `need_anchor_vip=true` requires public scope. `vip_levels` must contain only live values when supplied, but the official submit validation accepts an empty array. Turning only `need_anchor_vip` off preserves the existing level array; switching to private scope or switching the outer mode to free clears it.
- `creation_statement` is `original`, `chinesize`, `renovate`, or `second`.

Omission on edit preserves the remote value. Explicit false follows the field-specific official behavior: room and association children are cleared, while anchor VIP levels remain unless private scope or the outer free mode clears them.

## Plugin

`plugin create` fields: `game_type`, `scope`, `addon_type`, `name`, `description`, `logo`/`logo_file`, `detail_imgs`/`detail_img_files`, `primary_category_id`, `second_category_ids`, `html_desc`, `game_versions`, `detail_url`/`file`, `release_type`, `version`, `update_desc`, and all shared fields. Name, description, and version are at most 80 characters; update description is at most 1000; detail images are at most 8.

`game_type` and the outer free/paid state are create-only. `plugin update` requires `sn`, `game_versions`, `version`, and `update_desc`; optional `file`, `detail_url`, and `release_type` publish a new version. `plugin edit` requires `sn` and only accepts the official existing-record commercial and association controls (`scope`, payment/lifetime/VIP fields, room/channel linkage, `creation_statement`, and associated content). First-publication metadata (`addon_type`, `name`, `description`, logo, detail images, categories, and `html_desc`) and version fields are not edit fields; in particular, sending `description` to `/addon/modify` can be accepted while leaving the remote value unchanged, so the CLI rejects it instead of reporting a false success.

When rebuilding a plugin update/edit form, preserve field presence from the current DD record. A field absent from both official projections must remain absent; do not synthesize JSON `null`, because the official web `pick -> JSON.stringify` path omits absent properties and DD can reject synthetic nulls with HTTP 422. The official detail dialog is opened from the matching author-list item and takes `detail_url`, `release_type`, and `version` from that item's `latest_version`; `detail_v2` supplies the stable detail fields and top-level `game_versions`. Python therefore uses the same-SN author item only to fill null/missing latest-version placeholders, never to overwrite stable metadata or top-level builds.

Before `plugin update`, query `/addon/addon_versions` as an optional duplicate guard. If it returns version rows, reject any candidate version already present anywhere in that history before upload; if it is empty or unavailable, retain the current-version check and continue. After update, confirm the submitted version fields from the matching item in the author plugin list, whose `latest_version` is the official update projection. `detail_v2` is supplementary. An empty history never marks a successful private-plugin update as failed and never triggers replay.

Read `plugin categories`, choose `primary_category_id`, then choose only returned `second_category_ids`. Read `plugin game-versions --game-type <id>` and use its stable values. The package accepts `.zip` only. Authorization always uses `file_type=a19-ui-res`, `business_id=addon`, fixed `file_name=addon.zip`, and `mime_type=application/x-zip-compressed`. Plugin image authorization uses `a19-ui-media/img` with an explicit empty wire file name.

## Configuration share

`config create` fields: `backup_sn`, `scope`, `title`, `brief_desc`, `desc`, `update_desc`, `display_imgs`/`display_img_files`, `known_addon_ids`, `unknown_addon_ids`, `wtf_role_ids`, `material_names`, `font_names`, `known_wa_ids`, `unknown_wa_ids`, optional `retail_ui_config`, all incremental arrays, and shared fields. The incremental arrays are `known_addon_update_ids`, `unknown_addon_update_ids`, `material_update_names`, `font_update_names`, `known_wa_update_ids`, and `unknown_wa_update_ids`.

Title is at most 40 characters, brief description 50, update description 1000, and display images 8. `wtf_role_ids` contains at most one opaque selector returned by `config backup-get`.

Run `config backups`, select `backup_sn`, then run `config backup-get --sn <backup>`. Choose content references only from that response. After choosing one WTF role, filter known/unknown WA by the selected role's account. Switching backup requires complete reselection. Switching the WTF account clears both WA groups. Unknown WA internal IDs are restored by Python from `extra.wa_account_info[account]`; they never appear in input JSON.

Every wire content group is rebuilt from the latest backup. Each `inner_version` map covers every source item; a new entry is 1, an existing value is preserved, and only explicitly listed existing update entries increment.

For retail, `retail_ui_config` accepts `edit_mode_selectors`, `default_edit_mode_selector`, `cool_down_selectors`, and `enable_dd_setup_wizard`. Up to five edit modes are allowed and one selected mode is default. Only one cooldown per `spec_tag` is allowed. Selectors are bound to one backup; raw `import_string` and raw edit/cooldown objects are read-only and never emitted.

`config update` requires `share_sn`, `backup_sn`, and `update_desc`; it changes backup content and increments. `config edit` requires `share_sn` and changes metadata, images, and allowed shared fields only. Config images omit `file_name` from upload authorization.

## WA/string

`wa create` fields: `game_type`, `scope`, `name`, `game_version`, `brief_desc`, `display_imgs`/`display_img_files`, `category_ids`, `content`, `desc`, `update_desc`, `version`, `with_file`, optional local `file`, `file_install_path`, and all shared fields. Name is at most 40 characters, brief description 50, update description 1000, numeric version length 80, categories 5, and images 8.

Read `wa categories --game-type <id>` and use only that game type's category IDs. `game_type` and outer free/paid mode are locked after creation. `wa update` requires `sn`, `content`, `update_desc`, `version`, and `with_file`; the numeric version must increase. `wa edit` requires `sn` and accepts metadata, categories, images, and allowed shared fields.

The official create builder supplies defaults that are required even when the user did not make a business choice: `share_code_life_type="seven_day"`, `need_buy=false`, `buy_life_type="seven_day"`, `category_ids=["ui_original"]`, `file_install_path="Interface/Addons"`, `vip_levels=[]`, and `version="0"`. The CLI applies these only to create, then applies the user's explicit values and normalizes every submitted category ID to its string wire form. Update and edit preserve remote values for omitted fields rather than reapplying create defaults.

Every submit whose content begins `!WA:2!` is reparsed by the DD-native bridge, including unchanged content on edit. Internal `parse_wa_uid` and `parse_wa_id` are read-only wire fields and are not accepted in JSON. Non-WA2 clears them.

When `with_file=true`, create requires a local `.zip` `file` and nonempty `file_install_path`; update may preserve an existing material when `file` is omitted. Authorization uses `a19-ui-res/wa`, fixed `file_name=wa_materials.zip`, fixed ZIP MIME, and a 50 MiB local limit plus server `maxSize`. `with_file=false` follows the official builder and preserves existing internal `file_path` and install path rather than clearing them. WA images omit upload `file_name`.

## Delete

`plugin delete`, `config delete`, and `wa delete` each accept one nonempty `sn` and `confirm_delete`=true. Python GETs the target and ownership state before `/addon/delete`, `/share/delete`, or `/wa/delete`, then verifies absence through list/get readback. An uncertain delete is never automatically retried.

## Errors and readback

Stages are `session`, `dependency_get`, `upload_authorize`, `object_put`, `mutation`, `readback`, and `native_parser`. Explicit HTTP/business failures and all pre-mutation validation failures have `verification_required=false`. In particular, HTTP 4xx responses such as 422 are confirmed server rejections, not uncertain writes; the CLI reports `http_status` and a bounded, secret-free validation summary when the native response exposes one. PUT/mutation connection uncertainty and accepted-write readback uncertainty have `verification_required=true`; GET first and do not replay the write. Native failures retain a bounded exception message and the native `code`/`error_code` when present, with signed-URL query credentials, signatures, and tokens redacted before they leave the sidecar.

Each DD native/API failure appends one ASCII JSON line to `<DD version directory>/Fupload/logs/dd-errors-YYYYMMDD.jsonl`. The record includes HTTP status, native business code, stage, endpoint, request field names, the sanitized request JSON/body, validation hints, and the sanitized response JSON/body. Token, JWT, Cookie, authorization, credential, client identifier, signature, and signed upload URL fields are redacted recursively. Request and response bodies are independently bounded to 1 MiB by UTF-8 bytes and record their original size and truncation state. A log write failure is reported as `log_write_error` without replacing the original DD error.

After an accepted mutation, detail readback uses a short bounded GET-only poll and never resends the mutation. Plugin edit/version confirmation also checks the matching author-list projection because the official UI opens the modify dialog from that item while `detail_v2` can remain stale or contain null latest-version placeholders. Configuration readback compares its official integer `need_buy` wire value with the boolean detail projection through a resource-specific conversion.

The parent process and native sidecar exchange ASCII-only JSONL, and Fuploader's final JSON output follows the same rule. Non-ASCII request, response, and output text is represented with JSON Unicode escapes so Chinese titles, descriptions, announcements, and URLs do not depend on either Windows process code page. JSON consumers recover original UTF-8 strings through normal parsing.
