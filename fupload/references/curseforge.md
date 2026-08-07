# CurseForge reference

Use this reference only for CurseForge public author-project lookup and WoW plugin ZIP upload. Fuploader uses two independent official APIs and credentials.

## Contents

- [Capability boundary](#capability-boundary)
- [Local configuration](#local-configuration)
- [Public project lookup](#public-project-lookup)
- [Game versions](#game-versions)
- [Plugin upload](#plugin-upload)
- [Metadata contract](#metadata-contract)
- [Relations](#relations)
- [Plan, dry-run, and confirmation](#plan-dry-run-and-confirmation)
- [Success, visibility, and verification](#success-visibility-and-verification)
- [Errors and retry rules](#errors-and-retry-rules)
- [Official documentation](#official-documentation)

## Capability boundary

Fuploader supports:

- querying public World of Warcraft projects for one numeric author ID through the CurseForge Core API;
- listing Upload API game-version choices;
- uploading one ZIP to an existing World of Warcraft project.

It does not create projects, list an authenticated account's private/draft/pending-review projects, update an existing file, or delete a project/file. Create and inspect non-public projects in the [CurseForge Authors dashboard](https://authors.curseforge.com/). An empty Core API result means only that no matching public project was returned.

## Local configuration

Use `~/.fupload/curseforge.env`:

```dotenv
CURSEFORGE_AUTHOR_ID=
CURSEFORGE_API_KEY=
CURSEFORGE_UPLOAD_TOKEN=
```

- `CURSEFORGE_AUTHOR_ID`: non-secret positive integer used by public project lookup. It is an author membership/owner identifier, not an account username or project ID.
- `CURSEFORGE_API_KEY`: secret CurseForge for Studios/Core API key sent as `x-api-key`.
- `CURSEFORGE_UPLOAD_TOKEN`: secret Authors Upload API token sent as `X-Api-Token`.

The two secrets are not interchangeable. npm install/update creates the directory and template file when missing; an existing file is preserved byte for byte and is never backfilled or overwritten. Process environment values override file values for the current process. Never read, echo, log, copy into `publish/`, or request either secret in chat.

Check presence without exposing values:

```powershell
fupload curseforge session doctor
```

If the author ID is absent, ask for the numeric ID because it is non-secret, or use `--author-id` for that lookup. If a secret is absent, direct the user to fill the local file and rerun doctor.

## Public project lookup

Official request:

```http
GET https://api.curseforge.com/v1/mods/search?gameId=1&authorId=AUTHOR_ID&index=0&pageSize=50
Accept: application/json
x-api-key: CURSEFORGE_API_KEY
```

`gameId=1` selects World of Warcraft. The Core API defines `authorId` as filtering mods for which that author is a member; `primaryAuthorId` is the separate owner-only filter. `index` is zero-based, `pageSize` defaults to and is capped at 50, and `index + pageSize` cannot exceed 10,000.

Fuploader commands:

```powershell
fupload curseforge project list
fupload curseforge project list --author-id 138844367
```

Use `pagination.totalCount` as the count of matching public projects. Select the upload target by human-readable project name and returned numeric project ID. Do not interpret this response as a private account inventory.

## Game versions

Official request against the WoW Authors host:

```http
GET https://wow.curseforge.com/api/game/versions
X-Api-Token: CURSEFORGE_UPLOAD_TOKEN
```

The response entries contain `id`, `gameVersionTypeID`, `name`, and `slug`. Use the returned IDs or official names in upload metadata.

Fuploader command:

```powershell
fupload curseforge plugin game-versions
```

Fetch the current list immediately before planning an upload. Present selected names and IDs together; never derive IDs from version strings.

## Plugin upload

Official request:

```http
POST https://wow.curseforge.com/api/projects/{projectId}/upload-file
X-Api-Token: CURSEFORGE_UPLOAD_TOKEN
Content-Type: multipart/form-data; boundary=...

metadata=<JSON object>
file=<ZIP bytes>
```

The multipart request has the text field `metadata` and binary field `file`. The project ID comes from the existing project's overview URL/API record. On acceptance the official API returns JSON containing the new file `id`.

Fuploader accepts the strict schema `fupload.v1.curseforge.plugin.upload`:

| Field | Required | Contract |
| --- | --- | --- |
| `schema` | yes | Exactly `fupload.v1.curseforge.plugin.upload`. |
| `project_id` | yes | Positive integer for an existing project. |
| `file` | yes | Existing local ZIP path. |
| `changelog` | yes | Release notes string. |
| `changelog_type` | no | `text`, `html`, or `markdown`; official default is `text`. |
| `display_name` | no | Non-empty friendly file name. |
| `game_versions` | no | Non-empty array of numeric IDs from `plugin game-versions`; not supported with `parent_file_id`. |
| `game_version_names` | no | Array of non-empty official game-version names. |
| `release_type` | yes | `alpha`, `beta`, or `release`. |
| `parent_file_id` | no | Positive parent file ID; mutually exclusive with `game_versions` and `game_version_names`. |
| `relations` | no | Object described below. |
| `is_marked_for_manual_release` | no | Boolean; when true, approval does not immediately release the file. |

Compatibility fields are optional in the official API and executable schema. When supplied, use current values returned by `plugin game-versions`; do not combine `parent_file_id` with either version field. Example: [curseforge-plugin-upload.json](../examples/curseforge-plugin-upload.json).

```powershell
fupload curseforge plugin upload --input publish\20260807-120000-curseforge-plugin-upload\01-upload.json --dry-run
fupload curseforge plugin upload --input publish\20260807-120000-curseforge-plugin-upload\01-upload.json
```

The executable Fuploader JSON uses snake_case. The provider maps it to the official camelCase Upload API metadata keys.

## Metadata contract

The official Upload API documents these metadata fields:

| Official field | Fuploader field | Meaning and constraints |
| --- | --- | --- |
| `changelog` | `changelog` | Change description; HTML or Markdown requires matching `changelogType`. |
| `changelogType` | `changelog_type` | `text`, `html`, or `markdown`; optional, defaults to `text`. |
| `displayName` | `display_name` | Optional friendly display name. |
| `parentFileID` | `parent_file_id` | Optional positive parent file ID. Fuploader rejects it together with `gameVersions` or `gameVersionNames`. |
| `gameVersions` | `game_versions` | Optional array of numeric game-version IDs; not supported with `parentFileID`. |
| `gameVersionNames` | `game_version_names` | Optional array of game-version names. |
| `releaseType` | `release_type` | Required: `alpha`, `beta`, or `release`. |
| `isMarkedForManualRelease` | `is_marked_for_manual_release` | Optional manual-release flag. |
| `relations` | `relations` | Optional project dependency relations. |

Do not put official camelCase keys directly into Fuploader input; unknown fields are rejected. `project_id` and `file` select the endpoint/body file and are not members of the metadata JSON.

## Relations

Fuploader input mirrors the official relation shape while using snake_case for `projectID`:

```json
{
  "relations": {
    "projects": [
      {
        "slug": "related-project-slug",
        "project_id": 74924,
        "type": "requiredDependency"
      }
    ]
  }
}
```

Each item requires non-empty `slug` and `type`. `project_id` is optional and, when supplied, must be a positive integer for an exact project match. Unknown relation keys are rejected. Official relation types are:

- `embeddedLibrary`
- `incompatible`
- `optionalDependency`
- `requiredDependency`
- `tool`

The wire mapping is `slug`, optional `projectID`, and `type` inside `relations.projects`. Resolve and show each intended related project during planning; do not guess a slug or ID.

## Plan, dry-run, and confirmation

Create `publish/<YYYYMMDD-HHmmss>-curseforge-plugin-upload/01-upload.json`. Store only non-secret business fields and local file paths. Never store the API key or upload token.

Run `--dry-run` before confirmation. It validates strict JSON, field values, relation structure, and local file existence without authenticating, querying remote permissions, or uploading.

Present one complete plan containing:

- author ID and public project name plus project ID;
- ZIP path and inspected filename;
- selected game-version names plus IDs, or parent file ID;
- release type, changelog/type, display name, relations, and manual-release value;
- the exact `fupload curseforge plugin upload --input ...` command;
- the effects boundary: acceptance is not approval, release, or public visibility.

Obtain one explicit confirmation for that exact plan. If any project, file, version, parent, relation, release type, or manual-release choice changes, present and confirm the changed plan. After confirmation, issue only one upload request.

## Success, visibility, and verification

The Upload API success response is a JSON object containing the new file ID. Record that literal ID and exit status. This verifies that CurseForge accepted the upload request, not that moderation completed or the file is publicly visible.

Visibility boundaries:

- Core project search lists public projects only and has no authenticated current-account inventory.
- Upload acceptance can precede processing, moderation, approval, manual release, and public visibility.
- `is_marked_for_manual_release=true` intentionally adds a later author release decision after approval.
- The public search/list response cannot verify private, draft, or pending-review state.

Fuploader does not expose an authenticated uploaded-file status/readback endpoint. Use the returned file ID as the acceptance record and inspect the Authors dashboard when a later state must be confirmed. Do not describe acceptance as publication.

## Errors and retry rules

Interpret responses conservatively:

| Result | Meaning and action |
| --- | --- |
| Local schema/file error | No request was sent. Correct the input and rerun dry-run. |
| `400`/`422` | Metadata, version, relation, or multipart validation was rejected. Do not retry unchanged input. |
| `401` | Credential missing, invalid, or expired. Regenerate/configure locally; never request it in chat. |
| `403` | Token lacks permission for the project/action. Recheck project ownership and token scope locally. |
| `404` | Host, project, or endpoint was not found. Confirm the WoW host and project ID. |
| `409` | Treat as a conflicting/duplicate state; inspect the project before another write. |
| `429` | Rate limited. Honor `Retry-After` when supplied; do not loop. |
| `5xx` after request transmission | Outcome may be uncertain. Inspect the Authors dashboard before retrying. |
| Network interruption/timeout during upload | Outcome is uncertain. Never automatically resend; check the project/file list first to prevent duplicates. |

Expose only sanitized status, error kind, stage, and provider message. Never include request headers, secret values, or raw multipart bodies in output or logs.

## Official documentation

- [CurseForge for Studios introduction](https://docs.curseforge.com/docs/curseforge-for-studios/intro)
- [CurseForge Core REST API](https://docs.curseforge.com/rest-api/): base URL, `x-api-key`, pagination, and `GET /v1/mods/search` including `authorId`/`primaryAuthorId`.
- [CurseForge Upload API](https://support.curseforge.com/en/support/solutions/articles/9000197321-curseforge-upload-api): token generation, `X-Api-Token`, `GET /api/game/versions`, multipart `POST /api/projects/{projectId}/upload-file`, metadata, relations, and success file ID.
- [CurseForge Authors dashboard](https://authors.curseforge.com/): project creation and non-public author state.
