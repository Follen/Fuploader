# NetEase DD field and workflow reference

## Native session

Use `dd session doctor`, then a read command. Fupload checks `FUPLOAD_DD_DIR`, a running `netease_dd.exe`, Windows uninstall records, bounded DD user-config JSON, and standard installation roots. It validates each candidate, selects the highest installed version, and runs that version's `netease_dd.exe` with DD-native login and signing modules. `FUPLOAD_DD_EXPECTED_VERSION` may pin an exact version for troubleshooting. Do not request a token, credential database, or `clientNo`.

The stable sidecar device state is `%APPDATA%/CCVoiceHub/Fupload/sidecar-device.json`. Invalid state fails closed. One Fupload sidecar per Windows user may run while the normal DD GUI remains open.

Before writes, query `dd options game-types`, `channels`, `life-types`, `vip-levels`, and `associated-acts`, plus resource categories/game versions/backups. `life-types` exposes the official client enum; the similarly named `/act/life_type_cfgs` endpoint is season availability data, not these form values. All page-selectable business values are user choices.

## Shared commercial fields

All three resource create/edit schemas expose:

| Field | Rule |
| --- | --- |
| `scope` | Required on create: `public` or `private`. |
| `share_code_life_type` | Private/free lifetime choice; required when `scope=private`; public is forced by DD to `forever`. |
| `need_buy` | Required create switch. When true, `price_fen` and `buy_life_type` are required. |
| `price_fen` | Price in fen. UI yuan must be converted explicitly. |
| `jump_room` | Required create switch. When true, `room_id` is required. |
| `room_id`, `channel_id`, `channel_type` | Live room/channel selection; channel ID and type move together. |
| `sync_room` | Allowed only for public, room-linked content; otherwise false. |
| `creation_statement` | Required create declaration selected from the platform enum. |
| `with_associate` | Required create switch; true requires non-empty `associated_acts`. |
| `associated_acts` | Complete array of `{sn,act_type}`. |
| `need_anchor_vip` | Required create switch; true requires `vip_levels`; private forces false. |
| `vip_levels` | Complete selected membership levels. |

Edit omission preserves current values. Explicit false clears dependent room, association, synchronization, or VIP fields.
Explicit `need_buy=false` clears `price_fen` and retains or fills the frontend's `seven_day` `buy_life_type`; the value is checked against `dd options life-types`. `need_buy=true` requires a positive `price_fen` and a `buy_life_type`. `jump_room=true` requires the full `room_id`/`channel_id`/`channel_type` tuple from `dd options channels`; this is an option-source read, not channel message access.

## Plugin

`plugin create` fields include required `game_type`, `scope`, `addon_type`, `name`, `description`, `primary_category_id`, `game_versions`, `release_type`, `version`, `html_desc`, `update_desc`, `creation_statement`, and shared switches. One of `logo` or `logo_file`, one of `detail_imgs` or `detail_img_files`, and one of `detail_url` or `file` is required. Optional `second_category_ids` exposes the complete secondary selection.

`plugin update` requires `sn`, `game_versions`, `version`, `update_desc`; it may replace `detail_url` through `file` and select `release_type`. It first GETs detail and versions, then calls `/addon/modify` with the complete plugin form.

`plugin edit` requires `sn`; all metadata and shared commercial fields are optional/presence-aware. It does not accept version fields. Read choices with `plugin categories`, `plugin game-versions`, and `plugin versions`.

## Configuration share

`config create` requires `scope`, `backup_sn`, `title`, `brief_desc`, `desc`, `creation_statement`, shared switches, and explicit full-selection arrays: `known_addon_ids`, `unknown_addon_ids`, `wtf_role_ids`, `material_names`, `font_names`, `known_wa_ids`, `unknown_wa_ids`. One of `display_imgs` or `display_img_files` is required. `update_desc` is optional because the production page does not require it. `wtf_role_ids` accepts at most one role because DD selects one WTF account context; `known_wa_ids` and `unknown_wa_ids` use the safe `uid` references returned by `backup-get` and must be available in that selected account's `accounts` list. Changing the WTF account clears omitted WA groups, and unknown WA objects receive the account-specific internal `id` automatically.

The content schema also exposes per-group incremental arrays: `known_addon_update_ids`, `unknown_addon_update_ids`, `material_update_names`, `font_update_names`, `known_wa_update_ids`, and `unknown_wa_update_ids`.

For a retail (`game_type=10001`) backup, `config backup-get` exposes a safe `retail_ui_config` catalog. Each edit-mode or cooldown entry has an opaque selector and non-sensitive display metadata; raw `import_string` values are never output. The write input accepts only:

- `edit_mode_selectors`: zero to five selectors;
- `default_edit_mode_selector`: required when at least one edit mode is selected and must name one selected item;
- `cool_down_selectors`: at most one selector for each `spec_tag`;
- `enable_dd_setup_wizard`: explicit boolean.

Selectors are bound to one backup and are resolved internally to the complete raw objects immediately before the write. Cross-backup selectors, raw `edit_mode`/`cool_down` objects, duplicate selectors, more than five edit modes, and two cooldown choices for one `spec_tag` are rejected. A new or changed retail backup requires an explicit `retail_ui_config`; `null` explicitly clears it. On an unchanged retail backup, omission preserves the current value and a partial selector object changes only the named section. Non-retail backups reject a non-null retail selection.

`config update` requires `share_sn`, `backup_sn`, and `update_desc`. If the backup changes, provide all full-selection arrays for the new backup. For the same backup, omitted groups preserve existing selections. Incremental arrays bump only existing `inner_version` keys.

`config edit` requires `share_sn` and exposes only title/brief/description/images plus shared commercial fields. It cannot change backup content.

The builder reads `/share/detail`, `/backup/list`, and `/backup/detail`; reconstructs `known_addon`, `unknown_addon`, `wtf`, `material`, `font`, `known_wa`, `unknown_wa`, and selector-resolved `retail_ui_config`; then uses `/share/create|modify`. Selecting any plugin requires at least one WTF role. WA-only content does not satisfy DD's non-empty content check.

## WA/string

`wa create` requires `game_type`, `scope`, `name`, `game_version`, `brief_desc`, `category_ids`, `content`, `desc`, `update_desc`, `version`, `creation_statement`, `with_file`, and shared switches. One of `display_imgs` or `display_img_files` is required.

Material fields are `with_file`, `file_path`, `file`, and `file_install_path`; provide either the existing `file_path` reference or a local `file`. A local material ZIP uploads with DD business `wa` and server limit (observed page limit 50 MiB). When `with_file=false`, path/install fields are cleared.

WA2 strings beginning `!WA:2!` require `parse_wa_uid` and `parse_wa_id` obtained through DD-native parsing; non-WA2 input clears both. `file_install_path` choices are `Interface/Addons`, `Interface`, or game root, subject to live page options.

`wa update` requires `sn`, `content`, `update_desc`, `version`, and `with_file`; optional material and parse fields update content without metadata changes. Version must be greater than the current version.

`wa edit` requires `sn` and exposes metadata, images, categories, and shared commercial fields only. All writes use resource-specific detail-to-form and allowlisted `/wa/create|modify` payloads.
