# ModUs.Creator

The ModUs provider reuses the local Windows Creator login state from
`%LOCALAPPDATA%\ModUs.Creator\auth\token.dat`. The file is decrypted with
CurrentUser DPAPI and the fixed entropy `ModUs.Creator.TokenStore.v1`; token
contents, cookies, and signed URLs are never accepted as input or printed.

## Read operations

`modus session doctor` reports only `token_present`, `token_decrypted`,
`token_nonempty`, and `api_ready`. API readiness is a real read-only
`system/user/getInfo` probe.
`modus project list|get` reads author projects. `modus plugin list|get|versions`
reads release records. `modus options categories|game-versions|subscription-tiers`
reads dynamic choices returned by the service. `categories` uses Creator's
`GET plugin/list/Categories`; `subscription-tiers` uses `GET
user/author/subscription/tiers`; `game-versions` uses `POST
game/data/config/detail` with a JSON `{"keys": [...]}` body. Repeat `--key`
to request selected server-defined configuration keys; at least one key is
required because the service rejects an empty list.

Main-client form choices are available through `modus options config-tags`,
`modus options wa-tags`, and `modus options wa-support-addons`. These commands
read the official ModUs static client-data origin without sending the local
login token.

## Project writes

`modus project create|edit|delete` uses versioned JSON through `--input`.
The complete project model includes `project_id`, `name`, `alt_name`, `summary`,
`categories`, `synchronization_type`, `license`, `images`, `repo_url`,
`required_tier_id`, `required_dependencies`, `cf_url`, returned `logo`, `status`,
`game`, and `description`. Write inputs use `project_state`, `publish_platforms`,
`logo_base64`, the compatibility `screenshot_base64s`, and edit-only `image_ops`.

### Project field contract

| CLI/state field | Creator wire/readback | JSON type | Required/default | Source and state dependency | Successful readback |
| --- | --- | --- | --- | --- | --- |
| `schema` | none | string | required by every write document | versioned CLI envelope | not sent |
| `project_id` | `projectId` | positive integer | edit/delete required; create assigned by server | outer write document, not form state | `projectId` |
| `game` | none confirmed | object or non-empty string | required; no default | `choose_game`; object needs a stable ID/key | preserved in state snapshot |
| `name` | `name` | non-empty string | required; no default | `basic_info` | `name` |
| `alt_name` | `altName` | string/null | optional; omitted preserves value | `basic_info`; edit clear uses `<null>` | `altName` |
| `summary` | `summary` | non-empty string | required; no default | `basic_info` | `summary` |
| `categories` | comma-delimited `categories` | 1-5 positive integer IDs | required; no default | service `categories` enum; `basic_info`; ID 998 requires BigFoot only | comma-delimited `categories` |
| `publish_platforms` | derived `synchronizationType` | non-empty unique enum array | required; no default | `basic_info`; values `modus`, `bigfoot`, or both | integer `1`, `2`, or `3` |
| `synchronization_type` | `synchronizationType` | integer | derived; caller value is replaced | derived from platform toggles in `basic_info` | `synchronizationType` |
| `required_tier_id` | `requiredTierId` | nullable positive integer input | omitted means no tier | service `subscription-tiers` enum; current result is `[]`; BigFoot requires no tier | omitted from the wire for no tier |
| `repo_url` | `repoUrl` | string/null | optional; omitted preserves value | `basic_info`; create empty is omitted; edit clear uses `<null>` | `repoUrl` |
| `logo_base64` | `screenshotBase64sReqs.screenshotBase64s` | base64 string | optional; default empty string | create-only `basic_info`; sent as `logo.webp` | server-managed `logo` path |
| `screenshot_base64s` | same create logo payload | string array | compatibility alias; default empty array | create-only `basic_info`; first value is used when `logo_base64` is absent | server-managed `logo` path |
| `license.type` | `license` JSON string `type` | non-empty string | required; no default | separate `license` step | parsed `license` |
| `license.holder/year/content` | fields inside `license` JSON string | non-empty strings | optional except custom content | separate `license` step; custom requires content | parsed `license` |
| `description` | `description` | string/null | edit-only; omitted preserves value | edit `basic_info`; clear uses `<null>` | `description` |
| `required_dependencies` | `requiredDependencies` | string/null | edit-only; omitted preserves value | edit `basic_info`; clear uses `<null>`; dependency query is dynamic | `requiredDependencies` |
| `images` | `images` | non-negative integer | edit-only; required with `image_ops` | edit `basic_info` | `images` count |
| `image_ops` | `imagesOps` | operation array | edit-only; no default | edit `basic_info`; upload requires base64, delete forbids it | `images` count |
| `cf_url` | `cfUrl` | string/null | read-only | known detail field may be preserved in a snapshot but is never sent | `cfUrl` |
| `logo` | `logo` | string/object/null | read-only | server-managed detail field; create uses `logo_base64` instead | `logo` |
| `status` | `status` | integer/null | read-only | server-managed detail field | `status` |
| `project_state` | none | object | required and must be `complete` | wraps `choose_game -> basic_info -> license`; unknown nested fields are rejected | local resumable snapshot |

Create-only, edit-only, and read-only fields may be preserved in a resumable
snapshot, but `_project_wire` sends only fields supported by the selected API
operation. The state machine rejects unknown `basic_info` and `license` fields
before changing state.
`publish_platforms` is a non-empty array containing `modus`,
`bigfoot`, or both; the two values are not mutually exclusive. Creator derives
wire `synchronizationType` as 1 for ModUs, 2 for BigFoot, and 3 for both.
When BigFoot is selected, `required_tier_id` must be null or omitted. Category ID 998 is
BigFoot-exclusive and forces BigFoot as the only platform. `categories` contains
one to five positive integer IDs.

Create sends `name`, `altName`, `summary`, comma-delimited `categories`,
`synchronizationType`, `license`, `images: 0`, `screenshotBase64sReqs`, optional
`repoUrl`, and optional positive `requiredTierId`. `logo_base64` is the payload
named `logo.webp`; `screenshot_base64s` remains the compatibility alias.
`license` is the JSON string generated from `type`, `holder`, `year`, and
`content`.

Edit sends only changed Creator fields plus `projectId`. `description`, cleared
`repo_url`, cleared `alt_name`, null `required_tier_id`, and cleared
`required_dependencies` use Creator's literal `<null>` marker. `image_ops` maps
to `imagesOps` entries with `op` (`upload` or `delete`), `name`, and upload-only
`base64`; `images` is required with image operations. `cf_url`, returned `logo`,
and `status` are read-only/server-managed. `publish_platforms` and `game` are
local form state, not project update keys.
`project_state` is a resumable `choose_game` -> `basic_info` -> `license` ->
`complete` snapshot and is required for both create and edit; incomplete or
missing snapshots are rejected before dry-run or network access. Each step preserves
its state on validation failure. `required_tier_id` is null or omitted for the
no-tier branch and is omitted from the HTTP payload; a selected tier is a
positive dropdown ID.
The write document also accepts `confirm` for destructive operations.
Deletion requires `confirm: "DELETE"`.

## Plugin release writes

`modus plugin create|upload|update|edit|delete` uses the release fields
`project_id`, `file_id`, `version`, `type`, `supported_game_versions`, `md5`,
`zip_size`, `unzip_size`, `path`, `toc_version`, `changelog`, and `file`.
`transaction_log` optionally selects the redacted transaction record path.
Successful records include the completed `file_id`, metadata, signature, and
binary upload stages that ran; failed records include `failed_stage`, a redacted
error, and whether the ZIP was retained. The transaction record is established
before file-ID allocation and ZIP preflight, so those early failures are also
durable. Binary-upload errors expose only a query-free endpoint identifier,
status when available, and a bounded redacted response summary. The provider parses every ZIP `.toc`
`Interface` value to derive
`toc_version` and `supported_game_versions`; explicit caller values must match.
The provider validates the ZIP, computes `md5`, `zip_size`, and `unzip_size`,
registers metadata, obtains a signed URL, then uploads the ZIP bytes with HTTP
`PUT` and `Content-Type: application/zip`. A local path is metadata only; it is
never substituted for the binary upload. Release deletion requires
`confirm: "DELETE"`.

All write commands support `--dry-run`, which validates the versioned JSON and
local files without constructing an authenticated provider or making a request.

## Main ModUs client: configuration shares

The installed main client stores its Chromium session under `%APPDATA%\modus\Local Storage\leveldb`.
Fupload reads the persisted `token`/`deviceId` pair and calls the fixed
`https://app.modus.cool/api` origin with the raw `Authorization` value and
`X-Device-Id`; values are never printed. The Creator DPAPI store remains a
separate authentication source for `project` and `plugin` commands.

The configuration surface uses:

* `GET /system/user/backup/list`, `GET /system/user/backup/detail/{id}`
* `POST /system/user/backup/update`, `DELETE /system/user/backup/delete/{id}`
* `POST /system/user/share/list`, `POST /system/user/share/detail`
* `POST /system/user/share/create`, `PUT /system/user/share/update`,
  `DELETE /system/user/share/delete/{id}`

Share write fields are `share_id`, `addons_id`, `account_name`, `backup_id`,
`content`, `content_text`, `image_url`, `is_paid`, `is_public`, `price`,
`share_type`, `tags`, `title`, `exclude_wtf`, `role_name`,
`required_tier_id`, `sub_type`, optional low-level `platform` /
`synchronization_type`, and
`server_type`. `exclude_wtf` is a binary state: when it is `1`, account and
role are empty; when it is `0`, an account is required and a selected role is
optional. `sub_type=0` is the normal subscription mode; `sub_type=1` is the
season mode. Both modes allow the "none" tier represented by null or omitted
`required_tier_id`; Fupload omits `requiredTierId` from the wire in that branch.
A selected tier must be a positive ID returned by the service. The official
configuration form's submit object omits `platform` and `synchronizationType`.
Fupload's low-level API surface nevertheless exposes the backend fields: list
defaults `platform=0`, create defaults `platform=1` and
`synchronizationType=1`, and explicit low-level values are passed through.
`backup_id`, content, cover, title, and tags are required for create;
update is presence-aware and uses `share_id`. `addons_id` must be non-empty,
the trimmed title must contain at least 6 characters, tags contain 1 to 3
comma-delimited IDs, and plain `content_text` must contain more than 20
characters.

Backup rename uses `backup_id`, `backup_name`, and `server_type`; backup
deletion uses `backup_id`, `confirm`, and `server_type`.

## Main ModUs client: strings

String articles use:

* `POST /system/user/import/list`, `POST /system/user/import/detail`
* `POST /system/user/import/create`, `POST /system/user/import/update`
* `DELETE /system/user/import/delete/{id}`
* `POST /system/user/import/version/publish`
* `DELETE /system/user/import/version/delete?versionId={id}`

String fields are `import_id`, `code_text`, `content`, `addons_id`,
`content_text`, `file_path`, `image_url`, `is_paid`, `is_public`, `price`,
`share_type`, `support_addon`, `tags`, `title`, `version`, `required_tier_id`,
`sub_type`, and `server_type`. The client requires a supported addon,
non-empty rendered/plain article content, cover, title, tags, and version.
`sub_type` and `required_tier_id` follow the same normal/season state machine.
The current account uses the no-tier branch, so `requiredTierId` is absent from
the wire. The official string form's submit object omits `platform` and
`synchronizationType`; Fupload's low-level API surface defaults list
`platform=0` and create/update `platform=1` / `synchronizationType=1`, while
preserving explicit values.
The trimmed title must contain at least 6 characters, tags contain 1 to 3
comma-delimited IDs, plain `content_text` must contain more than 20 characters,
and `file_path` is the client's fixed empty string. Version history is separate
from article metadata:
`version-publish` takes `import_id`, `version`, `code_text`, and optional
`changelog`; `version-delete` takes `version_id` and `confirm: "DELETE"`.

Both main-client modules support explicit `confirm: "DELETE"` on destructive
commands. List operations send only server fields (`pageNum`, `pageSize`,
`keyword`, status/filter values), not the local CLI envelope or `server_type`.
### Main-client resource IDs and deletion

Configuration-share and string/import IDs are opaque decimal strings (for example, 16-digit IDs), not the numeric backup/project IDs. Fupload preserves them as strings. ModUs delete is a soft-delete: a successful `DELETE` returns code `200`, and a subsequent detail may return the record with `status=4` and `isPublic=0`; regression treats that state as deleted.
