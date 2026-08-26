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

The table below is the A2 field inventory. `C` means create, `U` update/edit,
and `D` delete. The current CLI's Creator endpoints are `C POST
/game/data/author/project/release`, `U POST /game/data/author/project/update`,
`D POST /game/data/author/project/delete/project/{projectId}`, and readback is
`GET /game/data/author/project/detail/{projectId}` unless stated otherwise.

| CLI/state field | Creator wire name | JSON type | Required/default | Enum/source | State/linkage rule | Write endpoint | Detail/readback location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `schema` | not sent | string | required for each CLI write | schema registry | must match action | local validation only | not applicable |
| `project_id` | `projectId` | positive integer | U/D required; C server-assigned | project list/detail | outer document, not `project_state` | U/D | `projectId` |
| `game` | not sent by current CLI | object or non-empty string | required; no default | Creator game selector | first `choose_game` state; stable key/ID required | local state only | `project_state.game`; server version binding is separate |
| `name` | `name` | non-empty string, max 120 | required; no default | free text | `basic_info` | C/U | `name` |
| `alt_name` | `altName` | string/null, max 120 | optional; omitted preserves | free text | U clear becomes literal `<null>` | C/U | `altName` |
| `summary` | `summary` | non-empty string, max 500 | required; no default | free text | `basic_info` | C/U | `summary` |
| `categories` | comma-delimited `categories` | array of 1-5 positive IDs | required; no default | `GET /plugin/list/Categories` | ID `998` forces BigFoot-only | C/U | comma-delimited `categories` / category detail |
| `publish_platforms` | derives `synchronizationType` | unique array | required; no default | fixed `modus`, `bigfoot` | at least one; `[modus]=>1`, `[bigfoot]=>2`, both `=>3` | C/U through derived field | `synchronizationType` |
| `synchronization_type` | `synchronizationType` | integer `1..3` | derived; caller value replaced | derived from `publish_platforms` | must equal platform selection | C/U | `synchronizationType` |
| `required_tier_id` | `requiredTierId` | positive integer/null | default none: C omits; U null sends `<null>` | `GET /user/author/subscription/tiers` | BigFoot branch requires none | C/U | `requiredTierId`; absence is no-tier |
| `repo_url` | `repoUrl` | string/null, max 500 | optional | free URL text | C empty omitted; U clear sends `<null>` | C/U | `repoUrl` |
| `logo_base64` | `screenshotBase64sReqs.screenshotBase64s` | non-empty base64 string | C optional; default `""` | local image | C only; companion name fixed `logo.webp` | C | server-managed `logo` path |
| `screenshot_base64s` | same create logo member | base64 string array | compatibility alias; default `[]` | local images | current CLI consumes only first item when `logo_base64` absent | C | server-managed `logo` path |
| `license.type` | JSON-string `license.type` | non-empty string | required | Creator license selector | final `license` state | C/U | parse JSON-string `license` |
| `license.holder` | JSON-string `license.holder` | non-empty string | optional | free text | license step | C/U | parse JSON-string `license.holder` |
| `license.year` | JSON-string `license.year` | non-empty string | optional | free text | license step | C/U | parse JSON-string `license.year` |
| `license.content` | JSON-string `license.content` | non-empty string | custom license requires content | free text | license step/custom branch | C/U | parse JSON-string `license.content` |
| `description` | `description` | string/null, max 100000 | U only; omitted preserves | rich-text editor | clear sends `<null>` | U | `description` |
| `required_dependencies` | `requiredDependencies` | string/null, max 4000 | U only; omitted preserves | `POST /game/data/author/project/dependency/query` | clear sends `<null>` | U | `requiredDependencies` |
| `images` | `images` | non-negative integer | U required with `image_ops` | current detail count | count must agree with requested operations | U | `images` |
| `image_ops[].op` | `imagesOps[].op` | enum string | U operation required | fixed `upload`, `delete`, `rename` | upload/delete use `name`; rename uses `from/to` | U | `images`, logo/image paths |
| `image_ops[].name` | `imagesOps[].name` | non-empty string | upload/delete required | current object name | forbidden for rename | U | resulting image path/count |
| `image_ops[].base64` | `imagesOps[].base64` | base64 string | upload required; delete forbidden | local image | upload only | U | resulting image path/count |
| `image_ops[].from/to` | `imagesOps[].from/to` | non-empty strings | rename required | current/target name | rename only | U | resulting image paths |
| `cf_url` | `cfUrl` | string/null | read-only | server | never sent | none | `cfUrl` |
| `logo` | `logo` | string/object/null | read-only | server | C uses base64 input instead | none | `logo` |
| `status` | `status` | integer/null | read-only | server status enum | delete/publication state | none | `status` |
| `project_state` | not sent | object | required; state=`complete` | CLI state machine | exact order `choose_game -> basic_info -> license`; unknown fields rejected | local validation only | persisted CLI snapshot |

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
to `imagesOps` entries with `op` (`upload`, `delete`, or `rename`), `name` and
upload-only `base64`, or rename-only `from`/`to`; `images` is required with
image operations. `cf_url`, returned `logo`,
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

### Creator release/version field contract

This is the A4 inventory. Metadata create uses `POST
/game/data/author/project/upload`; metadata update/edit uses `POST
/game/data/author/project/file/update`; delete uses `POST
/game/data/author/project/delete`; detail is `GET
/game/data/author/project/file/detail/{fileId}` and history/list is `POST
/game/data/author/project/file/list`. File-ID allocation and the binary object
PUT are separate stages.

| CLI field | Creator wire name | JSON type | Required/default | Enum/source | State/linkage rule | Write endpoint | Detail/readback location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `schema` | not sent | string | required | schema registry | must match release action | local validation | not applicable |
| `project_id` | `projectId` | positive integer | all release writes required | project detail | parent project must exist | metadata create/update/delete; signature path | `projectId` in list/detail |
| `file_id` | `fileId` | positive integer | update/edit/delete required; upload allocates | `GET /game/data/author/project/fileId/{projectId}` | allocated ID is used by signature; create metadata omits it | update/delete/signature | `id`/`fileId` in release detail |
| `version` | `version` | non-empty string, max 120 | create/upload required after ZIP preflight | ZIP `.toc` plus caller label | caller value preserved | metadata create/update | `version` |
| `type` | `type` | non-empty string, max 40 | create/upload required | Creator release-type choices/API | must be a server-supported value | metadata create/update | `type` |
| `supported_game_versions` | `supportedGameVersionsReqs[]` | non-empty object array | required; ZIP-derived | installed `.toc` `Interface` values and game config | each entry requires string `gameVersion` and `server`; explicit caller value must match ZIP | metadata create/update | `supportedGameVersionsReqs`/version compatibility rows |
| `md5` | `md5` | hex string, max 64 | derived from exact ZIP bytes | local ZIP preflight | must describe bytes later PUT | metadata create/update | `md5` |
| `zip_size` | `zipSize` | non-negative integer | derived | local ZIP stat | must describe exact ZIP | metadata create/update | `zipSize` |
| `unzip_size` | `unzipSize` | non-negative integer | derived | ZIP central directory | bounded by ZIP preflight | metadata create/update | `unzipSize` |
| `path` | `path` | string, max 500 | metadata optional | Creator/object response | local path is never binary upload | metadata create/update | `path` |
| `toc_version` | `tocVersion` | string, max 80 | derived | every ZIP `.toc` `Interface` | incompatible/missing/mixed values fail before write | metadata create/update | `tocVersion` |
| `changelog` | `changelog` | string/null, max 10000 | optional | free text | omitted/empty behavior is action-specific | metadata create/update | `changelog` |
| `file` | not in JSON; raw bytes | local path | create/upload required | local filesystem | valid ZIP, max 200 MiB; bytes PUT only after metadata/signature | signed URL from `GET .../upload/signature/{projectId}/{fileId}`, then HTTP `PUT` | object upload status plus release detail hashes/sizes |
| `transaction_log` | not sent | local path string | optional | caller | redacted durable stage record | local record only | transaction JSON |
| derived signature URL | not returned to caller | URL | required for PUT | signature endpoint | query/userinfo redacted and never persisted | object-store `PUT application/zip` | HTTP status only; then release detail |

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

### Configuration list/filter contract

| CLI field | Wire/header name | JSON type | Required/default | Enum/source | State/linkage rule | Request endpoint | Readback location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `page_num` | `pageNum` | positive integer | default `1` | caller | list only | `POST /system/user/share/list` | pagination response |
| `page_size` | `pageSize` | positive integer | default `20` | caller | list only | same | pagination response |
| `server_type` / `server` | body `server`; header `X-Server-Type` | integer | local selected Build, fallback `0` | fixed Build table below | body and header must be identical | list; header on all config calls | list/detail records by Build |
| `mine` | `mine` | boolean | default `false` | fixed boolean | list only | list | returned rows |
| `share_type` | `shareType` | non-negative integer | default `0` | service/UI | list filter | list | returned rows |
| `platform` | `platform` | integer | list default `0` | service; write choices `1`,`3` | not Build | list | `platform` |
| `keyword` | `keyword` | string | optional | caller | list filter | list | returned rows |
| `status` | `status` | integer | optional | service status values | list filter | list | `status` |
| `tags` | `tags` | string | optional | `config-tags` static rows | list filter | list | tags on rows/detail |
| `order_by` | `orderBy` | service value | optional | service/UI | list sort | list | result order |
| `is_public` | `isPublic` | integer `0/1` | optional | fixed boolean | list filter | list | `isPublic` |
| `is_paid` | `isPaid` | integer `0/1` | optional | fixed boolean | list filter | list | `isPaid` |

### Configuration write field contract

This is the A6 inventory. Create is `POST /system/user/share/create`, update/edit
is `PUT /system/user/share/update`, delete is `DELETE
/system/user/share/delete/{id}`, and readback is `POST
/system/user/share/detail` with `{"shareIds":[id]}`. Every call carries the
selected Build in `X-Server-Type`.

| CLI field | Wire name | JSON type | Required/default | Enum/source | State/linkage rule | Write endpoint | Detail/readback location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `schema` | not sent | string | required | schema registry | must match action | local validation | not applicable |
| `share_id` | `id` / path ID | opaque decimal string | U/D required; C server-assigned | create response/detail | preserve as string | U/D | detail `id` |
| `addons_id` | `addonsId` | string, max 10000 | C required | selected backup `knownAddons.projectids` | must correspond to backup selection | C/U | `addonsId` |
| `backup_id` | `backupId` | positive integer | C required | `GET /system/user/backup/list` | account/role choices derive from this backup | C/U | `backupId` |
| `account_name` | `accountName` | string/null, max 120 | conditional | selected backup `wtfAccounts` | required and non-empty when `exclude_wtf=0`; empty when `1` | C/U | `accountName` |
| `role_name` | `roleName` | string/null, max 120 | optional in schema; UI requires selection when chosen account has roles | backup account roles | empty when `exclude_wtf=1` | C/U | `roleName` |
| `exclude_wtf` | `excludeWtf` | integer `0/1` | C required; provider normalizes missing U to `0` | fixed boolean | `1` forbids account/role; `0` requires account | C/U | `excludeWtf` |
| `content` | `content` | non-empty HTML string | C required | rich-text editor | editor image keys are uploaded before submit | C/U | `content` hash/length, not raw evidence |
| `content_text` | `contentText` | non-empty string | C required; trimmed length >20 | derived editor plain text | must correspond to `content` | C/U | `contentText` hash/length |
| `image_url` | `imageUrl` | non-empty comma-delimited key string, max 1000 | C required; 1-10 images in 1.2.16 UI | `modus media upload` results | trim/filter keys; first is cover; delete/reorder updates CSV, no blob-delete API observed | C/U | `imageUrl` |
| `is_paid` | `isPaid` | integer `0` | CLI optional; 1.2.16 form fixes `0` | installed client fixed value | nonzero values fail before mutation | C/U | `isPaid` |
| `price` | `price` | number `0` | CLI optional; 1.2.16 form fixes `0` | installed client fixed value | nonzero values fail before mutation | C/U | `price` |
| `is_public` | `isPublic` | integer `0/1` | CLI optional; 1.2.16 form defaults public | fixed boolean | visibility/soft-delete state | C/U | `isPublic` |
| `share_type` | `shareType` | integer `0` | CLI optional; 1.2.16 form fixes `0` | installed client fixed value | nonzero values fail before mutation | C/U | `shareType` |
| `tags` | comma-delimited `tags` | string of 1-3 IDs | C required | `modus options config-tags` | no empty/duplicate positions | C/U | `tags` and/or `modusShareTags` |
| `title` | `title` | string, max 120 | C required; trimmed length >=6 | free text | none | C/U | `title` |
| `required_tier_id` | `requiredTierId` | positive integer/null | default none: omitted | normal subscription or season option | selected tier disables BigFoot platform; ID from active options | C/U | `requiredTierId`; absence means none |
| `sub_type` | `subType` | integer `0/1` | helper default `0` | fixed normal=`0`, season=`1` | determines tier option source | C/U | `subType` |
| `platform` | `platform` | integer `1/3` | provider C/U default `1` | ModUs=`1`, ModUs+BigFoot=`3` | at least ModUs; tier selection forces `1` | C/U | `platform` |
| `synchronization_type` | `synchronizationType` | integer `1/3` | C defaults from platform; U omitted unless explicit | derived from platform | C should equal platform; 1.2.16 config U form omits it | C/U | `synchronizationType` if returned |
| `server_type` | header `X-Server-Type` | integer `0..4` | local selected Build or fallback `0` | fixed Build table | not `platform`; applies to target namespace | C/U/D/detail | record returned under same Build |
| `confirm` | not sent | literal `"DELETE"` | D required | fixed CLI guard | destructive action only | local guard then D | detail `status=4,isPublic=0`; absent from active list |

Backup rename uses `backup_id`, `backup_name`, and `server_type`; backup
deletion uses `backup_id`, `confirm`, and `server_type`.

## Main ModUs client: strings

String articles use:

* `POST /system/user/import/list`, `POST /system/user/import/detail`
* `POST /system/user/import/create`, `POST /system/user/import/update`
* `DELETE /system/user/import/delete/{id}`
* `POST /system/user/import/version/publish`
* `DELETE /system/user/import/version/delete?versionId={id}`

### WA/string list/filter contract

| CLI field | Wire/header name | JSON type | Required/default | Enum/source | State/linkage rule | Request endpoint | Readback location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `page_num` | `pageNum` | positive integer | default `1` | caller | list only | `POST /system/user/import/list` | pagination response |
| `page_size` | `pageSize` | positive integer | default `10` | caller | list only | same | pagination response |
| `server_type` / `server` | body `server`; header `X-Server-Type` | integer | local Build, fallback `0` | fixed Build table | body/header must match | list; header on every WA call | list/detail records by Build |
| `mine` | `mine` | boolean | default `false` | fixed boolean | list only | list | rows |
| `status` | `status` | integer | default `1` | service status enum | list only | list | `status` |
| `platform` | `platform` | integer | list default `0` | service; write `1/3` | not Build | list | `platform` |
| `keyword` | `keyword` | string | optional | caller | list filter | list | rows |
| `support_addon` | `supportAddon` | string | optional | `wa-support-addons` static rows | list filter | list | `supportAddon` |
| `tags` | `tags` | string | optional | `wa-tags` static rows | list filter | list | tags on rows/detail |
| `is_paid` | `isPaid` | integer `0/1` | optional | fixed boolean | list filter | list | `isPaid` |
| `order_by` | `orderBy` | service value | optional | service/UI | list sort | list | result order |

### WA/string write field contract

This is the A8 inventory. Create is `POST /system/user/import/create`,
update/edit is `POST /system/user/import/update`, delete is `DELETE
/system/user/import/delete/{id}`, and readback is `POST
/system/user/import/detail` with `{"importIds":[id]}`.

| CLI field | Wire name | JSON type | Required/default | Enum/source | State/linkage rule | Write endpoint | Detail/readback location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `schema` | not sent | string | required | schema registry | must match action | local validation | not applicable |
| `import_id` | `id` / path ID | opaque decimal string | U/D required; C server-assigned | create response/detail | preserve as string | U/D | detail `id` |
| `support_addon` | `supportAddon` | non-empty string, max 120 | C required | `modus options wa-support-addons` | chosen name must resolve to an addon row | C/U | `supportAddon` |
| `addons_id` | `addonsId` | non-empty string, max 10000 | C required | ID on selected support-addon row | must match `support_addon` | C/U | `addonsId` |
| `code_text` | `codeText` | non-empty string | C required; version publish required | WA/string input | create version and later version payload must be deliberate | C/U/version publish | current top-level `codeText` is not echoed; after the next publish, the previous current value is read from `versionList[].codeText` |
| `version` | `version` | non-empty string, max 120 | C required; U form preserves current | free text/version list | new immutable versions use version-publish | C/U/version publish | `version`, `versionList[].version` |
| `content` | `content` | non-empty HTML string | C required | rich-text editor | editor images uploaded before submit | C/U | `content` hash/length |
| `content_text` | `contentText` | non-empty string | C required; trimmed length >20 | derived plain text | must correspond to HTML content | C/U | `contentText` hash/length |
| `file_path` | `filePath` | literal empty string | optional in CLI; UI fixed `""` | fixed client behavior | only `""` accepted | C/U | `filePath` |
| `image_url` | `imageUrl` | non-empty comma-delimited key string, max 1000 | C required; 1-10 images in 1.2.16 UI | `modus media upload` results | first key is cover; delete/reorder rewrites CSV, no blob-delete API observed | C/U | `imageUrl` |
| `tags` | comma-delimited `tags` | string of 1-3 IDs | C required | `modus options wa-tags` | no empty positions | C/U | `tags` |
| `title` | `title` | string, max 120 | C required; trimmed length >=6 | free text | none | C/U | `title` |
| `is_paid` | `isPaid` | integer `0` | CLI optional; 1.2.16 form fixes `0` | installed client fixed value | nonzero values fail before mutation | C/U | `isPaid` |
| `price` | `price` | number `0` | CLI optional; 1.2.16 form fixes `0` | installed client fixed value | nonzero values fail before mutation | C/U | `price` |
| `is_public` | `isPublic` | integer `0/1` | CLI optional; 1.2.16 form fixes `1` | fixed boolean | soft-delete later forces private | C/U | `isPublic` |
| `share_type` | `shareType` | integer `0` | CLI optional; 1.2.16 form fixes `0` | installed client fixed value | nonzero values fail before mutation | C/U | `shareType` |
| `required_tier_id` | `requiredTierId` | positive integer/null | default none: omitted | normal/season tier options | selected tier disables BigFoot | C/U | `requiredTierId`; absence means none |
| `sub_type` | `subType` | integer `0/1` | helper default `0` | normal=`0`, season=`1` | selects tier option source | C/U | `subType` |
| `platform` | `platform` | integer `1/3` | C/U default `1` | ModUs=`1`, ModUs+BigFoot=`3` | at least ModUs; tier selection forces `1` | C/U | `platform` |
| `synchronization_type` | `synchronizationType` | integer `1/3` | C/U defaults from platform | derived | 1.2.16 sends it on both C and U | C/U | `synchronizationType` |
| `server_type` | header `X-Server-Type` | integer `0..4` | local Build or fallback `0` | fixed Build table | target namespace, not platform | C/U/D/detail/version | record under same Build |
| `confirm` | not sent | literal `"DELETE"` | D required | fixed CLI guard | destructive action only | local guard then D | `status=4,isPublic=0`; absent active list |

Version history is separate from article metadata:

| CLI field | Wire name | JSON type | Required/default | Enum/source | State/linkage rule | Write endpoint | Detail/readback location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `import_id` | `importId` | opaque decimal string | publish required | article detail | parent must exist | `POST /system/user/import/version/publish` | `versionList[].importId`/parent detail |
| `version` | `version` | non-empty string, max 120 | publish required | caller | expected immutable version label | same | `versionList[].version` |
| `code_text` | `codeText` | non-empty string | publish required | caller | content hash/length must match evidence | same | current top-level value is not echoed; publish the next version, then read the previous value from `versionList[].codeText` |
| `changelog` | `changelog` | string, max 10000 | optional; empty omitted | caller | version-specific | same | `versionList[].changelog` |
| `version_id` | query `versionId` | opaque identifier | delete required | `versionList[].versionId`/`id` | target exact version | `DELETE /system/user/import/version/delete?versionId={id}` | version absent from refreshed list |
| `confirm` | not sent | literal `"DELETE"` | version delete required | fixed CLI guard | destructive action only | local guard | refreshed `versionList` |

## Image upload and delete contract

There are three different image surfaces; they must not be collapsed into one
generic "image URL" test.

| Surface/CLI field | Official 1.2.16 wire | Input/preprocessing | Required headers | Response/reference | Delete behavior | Current CLI status/readback |
| --- | --- | --- | --- | --- | --- | --- |
| Creator logo: `logo_base64` / `screenshot_base64s` | C project JSON `screenshotBase64sReqs:{name:"logo.webp",screenshotBase64s:<base64>}` | prepared WebP base64 | Creator JSON auth | project `logo` path | U `imagesOps` upload/delete `logo.webp` | live create, replace, delete, restore and detail readback passed |
| Creator screenshots | U project JSON `imagesOps` | prepared WebP base64 for upload; names for delete/rename | Creator JSON auth | project `images` count | upload/delete use `name`; rename uses `from`/`to` | two-image upload, rename, single delete and final delete all passed with detail counts |
| Config cover/gallery: `image_url` | `POST /game/data/file/upload/file/image`, multipart field exactly `file`; one request per image | original local file; up to 10 comma-delimited references | raw `Authorization`, optional `X-Device-Id`; no `X-Server-Type` | key priority `cosStoreKey`, `cosStoreUrl`, `key`, then pathname of `downloadUrl/url/fileUrl`; CSV first key is cover | remove/reorder key in CSV and submit config U; no object-delete endpoint observed | two distinct local images uploaded with byte hashes; returned keys passed config C/U detail readback |
| WA cover/gallery: `image_url` | same endpoint and multipart `file`; one request per image | original local file; up to 10 comma-delimited references | same; no `X-Server-Type` | same key priority and CSV ordering | remove/reorder key in CSV and submit WA U; no object-delete endpoint observed | two distinct local images uploaded with byte hashes; returned keys passed WA C/U detail readback |

The 1.2.16 upload helper is `FormData.append("file", File)` and sets
`Content-Type: multipart/form-data`; the browser adapter supplies the boundary,
filename, and part MIME. The CLI multipart helper supplies a generated boundary,
uses the local basename, derives MIME through `mimetypes.guess_type`, and fixes
`.webp` to `image/webp`. A key-only response is accepted and its display URL is
synthesized. The CLI does not reproduce the UI's optional client-side image
compression; the final implementation's original-file upload was accepted by
the live service and the returned object keys were used in real C/U requests.

## Build and linked-state regression matrix

This is the A10 branch inventory. Positive rows were sent/read back where the
installed clients expose a writable branch; negative rows fail locally before
remote mutation.

| Branch | Positive cases | Negative case | Current implementation/gate |
| --- | --- | --- | --- |
| Build | `0 retail`, `1 classic_era`, `2 classic`, `3 classic_titan`, `4 anniversary`; for each, backup/config/WA list sends identical body `server` and `X-Server-Type` | `<0`, `>4`, non-integer | `_build` and schema reject outside `0..4`; all five live list triplets passed |
| Creator publish platform | ModUs-only `1`, BigFoot-only `2`, both `3` | empty, unknown, duplicate | state machine covers at-least-one/enum/duplicate |
| Creator category | 1-5 IDs from live categories | empty, >5, unknown/non-ID; `998` with ModUs/both | local count/linkage plus write preflight membership against `plugin/list/Categories`; real unknown positive ID fails before project mutation |
| Config/WA platform | omitted defaults ModUs `1`; explicit `1`; explicit ModUs+BigFoot `3` | `0`, `2`, other; mismatched platform/synchronization pairs | schema choices cover numeric invalids; write normalization requires the pair to be present together and equal; it is distinct from Build |
| Tier mode | normal `subType=0`, season `1`; each allows none by omitting `requiredTierId`; selected tier is positive dynamic ID | zero/negative/non-ID; ID absent from current normal/season options | write preflight reads the selected tier option set and rejects unknown IDs before mutation; the tested account exposes no tier, so real positive writes cover the no-tier branch |
| Tier + platform | no-tier allows platform `1/3`; selected tier forces platform `1` in UI | selected tier with platform/synchronization `3` | schema rejects tier+BigFoot; current account's live options are empty so real writes use the confirmed no-tier branch |
| Config WTF | `exclude_wtf=1` with empty account/role; `0` with an account and, when available, one of its roles | `1` with account/role; `0` without account; backup/account/role absent from the selected Build hierarchy; missing role when the account has roles | write preflight reads the selected Build backup hierarchy and rejects every invalid linkage before mutation |
| Tags | 1, 2, and 3 dynamic IDs | 0, 4, empty/duplicate CSV position, ID absent from the current config/WA tag options | schema covers count/shape/duplicates; write preflight binds every ID to the selected Build's current config/WA options before mutation |
| Paid/price | installed 1.2.16 forms submit fixed free `is_paid=0,price=0,share_type=0` | paid value, positive/negative price, or nonzero share type | schema/write preflight enforce the installed UI's fixed free branch; real field cycles cover exactly those values and do not claim an unavailable paid branch |
| Visibility | public `1`, private `0` where UI exposes it | other integer | schema enum covered; WA 1.2.16 form fixes public |
| Config/WA image CSV | 1 and 10 keys; first key is cover | empty C, >10, empty CSV entries, upload business code >=400 | schema enforces 1-10 non-empty references; media error and live C/U readback covered |
| Creator image ops | upload, delete, rename with matching required members | missing/extra member, upload without base64, delete with base64 | local validation plus live upload/rename/delete/readback covered |

### Acceptance coverage crosswalk

| Acceptance item | Matrix/evidence required here | Documentation status |
| --- | --- | --- |
| A2/A3 | Creator project table plus per-field C/U/readback/restore and logo/screenshot/image operations | `analyze/modus-creator/iteration4-live-regression.json`: passed, 140 steps; SHA-256 `7C7BE87959024A1431BC154B13830178815FFF32D23D55E4EAAED75B96B56E4B`; 126 positive exits `0`, 14 expected negative/not-found exits `2`, and unknown positive category membership fails before project mutation; CDN bytes matched local image SHA-256 after create/replace/delete/restore, then final project deletion made the restored logo return 404 |
| A4 | allocation, metadata, two distinct ZIP PUTs, detail, type/version/path edit/restore and cleanup | same evidence; ZIP SHA-256 and changed MD5/size recorded |
| A5-A9 | five Builds, config/WA per-field cycles, media upload, version rollover/readback/delete and cleanup | `analyze/modus/live-main-crud-builds-20260826.json`: passed, 209 steps/40 field checks; SHA-256 `298CD33D8E9B72E5AE7B63B6A82627622493CB2DC7476AFE61434E395312BB78`; 191 positive exits `0` and 18 negative exits `2`/`validation_error`; four media uploads carry nonempty byte/SHA-256 evidence for two different binaries, while account/role evidence stores presence only |
| A10 | linked-state table above, dynamic options and invalid combinations | live option selection plus schema/negative regression passed |
| A11 | commands, redacted input/response, exit status and content/image/ZIP digest evidence | both evidence records retain hashes instead of credentials or raw content |
| A19 | complete field names, wire names, types, defaults, sources, dependencies, endpoints and readback locations | matrices in this document |

Both main-client modules support explicit `confirm: "DELETE"` on destructive
commands. List operations send only server fields (`pageNum`, `pageSize`,
`keyword`, status/filter values), not the local CLI envelope or `server_type`.
### Main-client resource IDs and deletion

Configuration-share and string/import IDs are opaque decimal strings (for example, 16-digit IDs), not the numeric backup/project IDs. Fupload preserves them as strings. ModUs delete is a soft-delete: a successful `DELETE` returns code `200`, and a subsequent detail may return the record with `status=4` and `isPublic=0`; regression treats that state as deleted.
