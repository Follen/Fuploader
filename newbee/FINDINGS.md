# NewBeeBox 1.1.17 authentication findings

## Scope

The installed desktop client is Electron. The Windows uninstall entry says
`1.1.3`, while the extracted application package reports `1.1.17`.

- Install directory: `D:\Software\NewBeeBox`
- User data: `%APPDATA%\NewBeeBox`
- Package: `resources\app.asar`
- Package SHA-256: `2635D7FF026C05BB75A7551BD8603F8AB729FC67E34EF17A3D4F922E5F76891D`

## Local authentication state

The current client stores credentials as UTF-8 text in:

- `%APPDATA%\NewBeeBox\auth-store\access-token`
- `%APPDATA%\NewBeeBox\auth-store\refresh-token`
- `%APPDATA%\NewBeeBox\auth-store\device-proof`

Older versions used Electron `safeStorage` in `%APPDATA%\NewBeeBox\auth`.
Version 1.1.17 migrates those encrypted values into the current `auth-store`
directory and removes the legacy directory.

The access token is an HS256 JWT with a five-minute lifetime. The refresh token
and device proof are opaque values. Do not print or commit any of them.

## Refresh protocol

`POST https://api.next.newbeebox.com/auth/connect/token`

Content type: `application/x-www-form-urlencoded`

Fields:

- `client_id=nbb-desktop`
- `grant_type=refresh_token`
- `refresh_token=<local refresh-token>`
- `device_name=<Windows host name>`
- `device_type=desktop`
- `device_proof=<local device-proof>` when present

The response contains `access_token` and may rotate `refresh_token` and
`device_proof`. Returned values must be written back before another refresh.

## Creator Center handoff

The current public configuration is read from
`https://cdn2.newbeebox.com/modconfig.json` and contains:

```json
{
  "creator_center_config": {
    "url": "https://creator.newbeebox.com/",
    "enable": true
  }
}
```

The desktop client obtains a one-time browser login code with:

`POST https://api.newbeebox.com/v3/user/auth2web`

The normal API request wrapper sends:

- `Authorization: Bearer <access-token>`
- `boxid: <client installation id>` when available
- `boxversion: <client version>`
- `Accept-Language: <locale>`

On success, the client opens:

`https://creator.newbeebox.com/?auth_code=<response.data.code>`

This is why using Creator Center from the desktop client preserves login state
in the system browser. It is a one-time-code handoff, not cookie extraction.

## Safe local probe

The probe never prints credential values:

```powershell
node newbee/probe-auth.mjs status
node newbee/probe-auth.mjs check
node newbee/probe-auth.mjs creator-check
```

`refresh` follows the official client protocol and writes rotated credentials
back to `auth-store`. Do not run multiple refresh commands concurrently:

```powershell
node newbee/probe-auth.mjs refresh
```

`creator-check` performs the complete one-time-code handoff in memory and only
prints the author verification status. It never persists or prints the returned
`author_token` or resource token.

As of the inspected backend response, `exchange_web_code` returns `token` but
may omit the older optional `jwtToken` field. In that case the resource-token
refresh uses the `token` header without an initial Bearer token, matching the
current Creator Center frontend.

## Creator content types

The Creator Center contains four World of Warcraft publication types. Their
canonical frontend mappings are:

| Type | Frontend value | Menu ID | Main content |
| --- | --- | ---: | --- |
| Addon | `plugin` | 5 | Addon metadata plus version archives |
| WA/string | `string` | 6 | One WeakAuras string or a named collection |
| Guide/article | `guide` | 7 | Rich-text guide with optional attachments |
| Shared config | `shareConfig` | 8 | A published view of an existing cloud backup |

All Creator API requests use `POST https://api.newbeebox.com`, JSON unless an
upload endpoint says otherwise, and the authenticated headers described above.

## Read-only content probe

The following commands reuse the desktop login state and emit only content
IDs, titles, visibility/review state, and latest version where applicable:

```powershell
node newbee/probe-creator.mjs addon
node newbee/probe-creator.mjs wa
node newbee/probe-creator.mjs config
node newbee/probe-creator.mjs guide
node newbee/probe-creator.mjs all
```

The list endpoints and pagination conventions are:

| Type | Endpoint | Page fields | Response total |
| --- | --- | --- | --- |
| Addon | `/creator/wow/mod/publish_list` | `pagenum`, `pagesize` | `data.total` |
| WA/string | `/creator/wow/wa/mtg_uc_publish_list` | zero-based `offset`, `pagesize` | `data.total` |
| Shared config | `/creator/wow/share_config/publish_list` | zero-based `offset`, `pagesize` | `data.count` |
| Guide | `/creator/wow/guide/publish_list` | zero-based `offset`, `pagesize` | `data.count` |

Addon list rows do not contain a version. The frontend obtains it from
`POST /creator/wow/mod_file/mod_file_list` with `mod_id`,
`game_version_id`, `pagenum`, and `pagesize`; the displayed version is
`data.list[].t_display_name`.

The live read-only probe confirmed the current account can list all four
content types. No creator token is printed or persisted by the probe.

## Addon publication workflow

Create and edit metadata:

- `POST /creator/wow/mod/create`
- `POST /creator/wow/mod/edit`
- `POST /creator/wow/mod/publish_detail`
- `POST /creator/wow/mod/upload_media` as multipart field `file`

The metadata payload uses `mod_categories`, `content_origin`,
`content_format`, `name`, `description`, `intro`, `logo`, `screenshots`,
`share_state`, `subscribe_plan_level`, and `link_to_channel`. Edit also sends
`id`. The create page initially uses `share_state: 0`; after the first version
is uploaded, publishing publicly is an edit to `share_state: 1`, which submits
the content for review.

Publish an addon archive:

`POST /creator/wow/mod_file/upload_mod_file`

Multipart fields:

- `mod_id`
- `version`
- `game_version_list` as a JSON string
- `file`
- `changelog` when present
- `link_to_channel` when present

The page accepts `.zip`, `.rar`, and `.7z`, limits the archive to 300 MB, and
sets a ten-minute request timeout. Version/history helpers are
`/creator/wow/mod_file/mod_file_list`, `changelog_list`, `get_changelog`, and
`edit_changelog`.

## WA and string publication workflow

Primary endpoints:

- `POST /creator/wow/wa/publish`
- `POST /creator/wow/wa/update`
- `POST /creator/wow/wa/update_wa_str`
- `POST /creator/wow/wa/get_next_version`
- `POST /creator/wow/wa_log/list`
- `POST /creator/wow/wa/upload_media` as multipart field `file`

New WA/string metadata includes `game_version_id`, `name`, `intro`,
`description`, `content_format`, `thumbnail`, `images`, `category_id_list`,
`content_origin`, `subscribe_plan_level`, `price`, `time_range`,
`share_state`, `link_to_channel`, `wa_str`, `wa_str_titles`, `wa_log`,
`string_mode`, and `attachments`.

`update_wa_str` publishes a new version with `id`, `version`, `wa_log`,
`wa_str`, `wa_str_titles`, and `link_to_channel`. A collection serializes
`wa_str` as a JSON array string and sends the parallel title array in
`wa_str_titles`; a single string does not need that collection encoding.

## Shared configuration publication workflow

A shared configuration is not an arbitrary ZIP upload. It must reference an
existing NewBeeBox cloud backup selected from:

`POST /creator/wow/share/list`

Publication endpoints:

- `POST /creator/wow/share_config/details_aps`
- `POST /creator/wow/share_config/release`
- `POST /creator/wow/share_config/update`
- `POST /creator/wow/share_config/upload` as multipart field `file` for images
- `POST /creator/wow/share_config/delete`

The release/update payload uses `cloud_id`, `title`, `content`,
`content_format`, `intro`, `pic_url`, `content_origin`, `sharing`,
`link_to_channel`, `subscribe_plan_level`, `price` in cents, `time_range`,
`linked_mods`, `ignored_unknown_mods`, `ignored_materials`, `ignored_fronts`,
and `roleid`. Update additionally sends `tid`.

Each `linked_mods` item contains `mod_id`, `mod_name`, `mod_file_id`,
`mod_version`, `display_name`, and `updateType`. The ignored lists are derived
from the selected backup. This means a CLI must inspect the backup and let the
caller make explicit association/exclusion choices before publication.

## Guide publication workflow

Primary endpoints:

- `POST /creator/wow/guide/create`
- `POST /creator/wow/guide/edit`
- `POST /creator/wow/guide/detail_aps`
- `POST /creator/wow/guide/category_list`
- `POST /creator/wow/guide/upload_media` as multipart field `file`
- `POST /creator/wow/guide/delete`

The create payload uses `title`, `content`, `intro`, `share_status`,
`subscribe_plan_level`, `content_origin`, `tags`, `cover`, `category_id`,
`game_version_id`, fixed `article_type: 2`, and an array of uploaded attachment
IDs. Edit adds `id`.

Attachments use `/creator/wow/guide/attachment_type_list`,
`attachment_extract_mode_list`, `upload_attachment`, `edit_attachment`, and
`remove_attachment`. `upload_attachment` is multipart with `type`, optional
`extract_mode`, `display_name`, `allow_download`, and `file`.

## Other upload protocol

The generic mod/package flow uses a separate multipart object-storage protocol
and is not the WoW addon archive endpoint:

1. `POST https://api.next.newbeebox.com/uploadserver/Upload/multipart/v2/init`
   with `fileSize` and `fileName`.
2. Upload each chunk to the returned `presignedUri[]` with `PUT`, in order,
   retrying a failed part at most three times.
3. `POST /uploadserver/Upload/multipart/v2/complete` with `uploadId` and `key`.

The init response supplies `totalChunks`, `chunkSize`, `uploadId`, `key`, and
the presigned URLs. This flow should not be reused for WoW addon versions.

## CLI boundary

The implementation should keep authentication and content operations separate:

```text
fuploader newbee auth status|check|refresh
fuploader newbee addon list|create|edit|publish-version
fuploader newbee wa list|create|edit|publish-version
fuploader newbee config list|backups|publish|edit
fuploader newbee guide list|create|edit
```

Read-only commands may automatically exchange the local desktop state for a
short-lived Creator session. Mutating commands should require explicit input,
show the target ID and effective publication/review state, and support a dry
run before any create, upload, edit, delete, or review submission.
