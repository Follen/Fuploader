---
name: fupload
description: Explicit author-publishing workflow for World of Warcraft plugins, configuration shares, and WA/strings on NewBeeBox, NetEase DD, CurseForge, Heybox Workshop, and ModUs.Creator, including local Creator login reuse and plugin ZIP publishing. Use only when the user explicitly invokes `$fupload`, explicitly asks to use the Fupload Skill, or loads this Skill by path. Do not trigger from ordinary mentions of publishing, NewBeeBox, DD, CurseForge, Heybox, ModUs, plugins, configurations, or WA.
metadata:
  version: "0.0.17"
---

# Fupload

Act as the publishing operator. For NewBeeBox, prefer the official `ncc` CLI whenever it is installed unless the user explicitly requests the third-party Python management tool. For DD, CurseForge, Heybox Workshop, ModUs.Creator, and an explicitly selected third-party NewBeeBox workflow, use the bundled Python CLI. Keep investigation, choices, planning, confirmation, and recovery in the conversation.

When installed from npm, interpret `<fupload-cli>` as `fupload`. Only while maintaining the source repository, directly installing this Skill, or when `fupload` is absent from PATH, use `python <skill-root>/scripts/fupload.py`. Keep the user's current project as the working directory in either mode.

## Establish intent

When the user has not already stated both dimensions, ask in one short message:

1. Platform: NewBeeBox, DD, CurseForge, Heybox Workshop, or ModUs.
2. Resource and action: plugin/configuration/WA, then create/content update/metadata edit/delete. CurseForge supports public project listing and uploading a plugin ZIP to an existing project only.

Map natural language consistently:

- `create`: create the main record. If first content is a separate platform action, plan it as a following atomic step.
- `update`: publish a plugin version, change selected configuration-backup content, or publish a WA/string version.
- `edit`: change fields allowed by the target platform's action allowlist. For DD plugins, this is existing-record commercial, association, room/channel, and creation-statement settings; first-publication metadata, categories, media, and version fields are create/update-only.
- `delete`: delete one main record only. It never deletes an individual version, media object, or associated record.

Never offer bulk delete, drafts, guides, messages, or GUI control automation. Heybox supports individual version deletion with asynchronous readback; whole-module deletion is not supported. The DD task-session command may close verified official GUI processes only after the consent flow below.

CurseForge cannot create a project or enumerate private, draft, or pending-review projects. Direct project creation to the Authors website; use the Core API list only as the public-project view for one numeric author ID.

## Select the execution channel

For DD, use the bundled Python CLI.

For CurseForge, use the bundled Python CLI. Do not substitute direct HTTP calls or the CurseForge for Studios API for uploads: public project lookup uses the Core API, while game-version lookup and upload use the separate Upload API and credential.

For ModUs, use the bundled Python CLI and the local ModUs.Creator login state. Do not use browser cookies, accept a caller-supplied token, or handcraft API requests.

For NewBeeBox, apply this order exactly:

1. If the user explicitly requests the third-party Python management tool, use the bundled Python CLI even when `ncc` is installed.
2. Otherwise detect `ncc` locally. On PowerShell use `Get-Command ncc -ErrorAction SilentlyContinue`; on POSIX shells use `command -v ncc`. Do not ask the user to report a fact the environment can show.
3. If installed, select official `ncc` by default. Run `ncc -V`, `ncc --help`, `ncc docs`, and `ncc whoami -o json`. Treat the installed `ncc docs` and target leaf `--help` as the execution contract. From `whoami`, retain or report only the creator identity and module permissions needed for the task; redact token names, prefixes, timestamps, and other credential metadata.
4. If not installed, ask whether the user wants the official CLI. If yes, check `node -v` is at least 18, help install Node.js when needed, then run `npm i -g @newbeebox/newbeebox-creator-center-cli@latest`. Verify `ncc -V` and `ncc --help`; installation success is not authentication success.
5. After installation, direct the user to `https://creator.newbeebox.com/creator-center/cli-token` to create a token and have them run `ncc login` in their own terminal. Resume only after `ncc whoami -o json` verifies the expected creator identity. For automation, accept an `NCC_TOKEN` already present in the Agent process environment without printing it.
6. If the user declines official installation, or official docs do not support the target action, explain the exact boundary. Use the Python channel only after the user explicitly chooses the third-party Python management tool.

Never switch channels silently. Before changing channels, re-read remote state and present a new plan so the same create, version, or edit cannot be submitted twice.

## Protect credentials

For NewBeeBox, prefer an existing official `ncc login`, then a caller-provided `NCC_TOKEN`, then user-performed local login. Never ask the user to paste a token into the conversation. Never place a real NewBeeBox token in `--token`, shell history, command output, JSON, `.env`, `publish/`, `analyze/`, tests, Skill files, references, or Git. Do not inspect or copy the official CLI credential store.

For CurseForge, use `~/.fupload/curseforge.env`, created idempotently by npm install/update, with `CURSEFORGE_AUTHOR_ID`, `CURSEFORGE_API_KEY`, and `CURSEFORGE_UPLOAD_TOKEN`. The author ID is non-secret: if absent, proactively ask for its numeric value or offer `--author-id`. The API key and upload token are secrets: never ask the user to paste either into the conversation; direct them to fill the local env file in their own editor or terminal, then run `curseforge session doctor`. Never print file contents or secret values. Process environment values may override the file without being shown.

For DD, reuse only the official client's local auto account and credential through `dd session start`. Never request or accept an email address, mobile number, password, token, credential value, or account-type override. Account and credential values must not appear in CLI output, plans, logs, tests, or analysis evidence; only the safe credential kind may be retained for diagnosis and verification.

For ModUs, authentication comes only from `%LOCALAPPDATA%\ModUs.Creator\auth\token.dat` under the current Windows user. `modus session doctor` reports only token presence, DPAPI decryption, nonempty plaintext, and authenticated API readiness. Never print, copy, hash, or persist the token, ciphertext, Bearer header, or signed upload URL.

If a token is pasted into the conversation, do not repeat or use it. Tell the user to revoke or regenerate it at its provider and configure the replacement locally. Check only whether the expected field is present, never its length, prefix, hash, or value.

## Locate the Fuploader CLI

Run `<fupload-cli> --help` from the user's project. The npm launcher resolves and verifies the installed Skill relative to the package, then invokes its bundled Python implementation; do not change the working directory to the Skill.

When the npm command is absent and the source/direct-Skill fallback is required, resolve `<skill-root>` from this `SKILL.md` and use `python <skill-root>/scripts/fupload.py`. On Windows, prefer `py -3` only if `python` is unavailable. Do not use a binary, Go source, repository-relative fallback, browser automation, Computer Use, or direct handcrafted HTTP calls. NewBeeBox's official `ncc` is not this bundled CLI and must not be wrapped as a Python `--input` command.

For npm package maintenance, use `fupload update` to update the CLI, managed Python runtime, and every registered managed Skill to `@follenfang/fupload@latest`. The npm installer and launcher create a Fuploader-only venv and install the pinned Python dependencies there; never ask for a system-wide `pip install`. For a complete removal, use `fupload uninstall`; it removes every registered Skill that still has a valid Fuploader npm ownership marker, the managed Python runtime, then the npm package and command. Do not use direct `npm install -g` or `npm uninstall -g` as the normal Agent-managed update/removal workflow.

## Load only the needed contract

- Read [references/workflow.md](references/workflow.md) for every write workflow.
- For official NewBeeBox, read [references/newbee-official-cli.md](references/newbee-official-cli.md), then run the installed `ncc docs` and exact leaf `--help`. The bundled reference is a complete official snapshot, but runtime docs win when versions differ.
- Read [references/newbee.md](references/newbee.md) only when the user explicitly selected the third-party Python NewBeeBox channel.
- Read [references/dd.md](references/dd.md) only for DD.
- Read [references/curseforge.md](references/curseforge.md) for every CurseForge lookup or upload.
- Read [references/blackbox.md](references/blackbox.md) for Heybox Workshop plugin list/detail, metadata edit, version upload/edit/delete, and managed web-session authentication.
- Read [references/modus.md](references/modus.md) for every ModUs project, addon discovery, release, upload, update, or delete workflow.
- For Python, run the exact leaf command with `--help` before creating its input. Treat help as the executable schema contract.

## Investigate

Inspect the user-provided project or current workspace for `.toc`, README, changelog, Git changes, archives, screenshots, logos, and WA material files. Do not modify or package the user's project until that is part of the agreed plan.

Use read-only commands from the selected channel to discover the current account's records, target detail, versions, backups, categories, game branches/builds, installation paths, life types, VIP levels, channels, and association candidates. Never ask the user to copy an ID that the selected CLI can query.

For CurseForge, run `curseforge session doctor`, then `curseforge project list` using `CURSEFORGE_AUTHOR_ID` or the user-provided non-secret `--author-id`. Select a public project by name plus `project_id`. Before a version-tagged upload, run `curseforge plugin game-versions` and select returned IDs or names; do not guess IDs from display names. A parent-file upload instead uses `parent_file_id` and omits both game-version fields. Inspect the ZIP and local release notes. An empty public list does not prove the account has no private, draft, or pending-review projects.

For official NewBeeBox, use the documented `ncc wow addons list|info|categories|versions`, `wa list|info|categories`, `uipack list|info`, `cloudbackup list|info`, and related commands needed by the action. Use the exact options returned by the installed help. `addons push` compatibility uses explicit build strings or documented `auto`; never substitute a parent branch ID. An empty required option list blocks the write.

For third-party Python NewBeeBox, use Creator Center webpage requests and form behavior as the business baseline. Always read `newbee options content-origins`, `subscribe-plans`, and `time-ranges` when the corresponding field is present. Also read plugin categories/builds, WA categories, attachment paths, and each resource's `co-author`/`reference` candidates for those fields. Empty option output blocks the write. Plugin compatibility uses build strings from `game-versions.items[].versions`, never the parent branch `id`. Preserve omitted edit fields; an explicit empty `co_authors` or `references` array replaces and clears that complete relation only after the main record readback succeeds.

For DD, use the one active task session to read game types/builds and the resource-specific category tree. Resolve parent/child choices in dependency order, display only children returned for the selected parent, and invalidate all descendants when a parent changes. A plugin primary category is a top-level item and secondary IDs are children of that item. Validate associations as `(act_type,sn)`. A room-only selection has `room_id` with empty `channel_id` and `channel_type`; a channel selection requires both channel fields. Query VIP levels only when anchor VIP is enabled and query room/channel data only when room linkage is enabled; disabled optional features do not depend on those endpoints.

For every existing DD update or edit, GET the detail first and rebuild the official full form before preparing the write. If a legacy record lacks a field now required by the official submit validator, such as `creation_statement`, stop before upload and collect that value. When the missing field belongs to a different action allowlist, plan and confirm the prerequisite edit first, read it back, then run the content update. Do not send `null`, create defaults, or guessed values to bypass the missing field.

For Heybox Workshop, use Fuploader's managed Chromium web profile. If the profile is missing or the creator API reports an expired session, Fuploader opens the Workshop login page visibly for the user to complete login, then reuses the same profile headlessly for signed protocol requests. Never read the desktop client config or import another browser profile, and never accept a caller-supplied profile, cookie, token, signature, or endpoint. `blackbox plugin list`, `get`, and `versions` are read-only; `plugin edit` preserves omitted module fields by reading the complete module first; `plugin update` and `version-edit` upload or reuse a ZIP URL and verify the version readback; `version-delete` waits for asynchronous soft deletion and retries once when the audit state temporarily returns active. Do not print cookies, tokens, signatures, or temporary COS credentials, and do not delete a whole module.

For ModUs, run `modus session doctor`, then read account info, project list/detail, categories, `game-versions --key wow_builds`, subscription tiers, and the target's release list/detail before writing. Project create/edit requires a completed persisted state in the order `choose_game -> basic_info -> license -> complete`. Publish targets are a nonempty multi-select: ModUs and BigFoot may coexist; ModUs-only, BigFoot-only, and both derive synchronization values 1, 2, and 3. Category `998` is BigFoot-only. Use the returned category IDs. When subscription tiers returns `[]`, “none” is the complete choice and `required_tier_id` remains null.

For DD WA create, collect user choices before generating JSON, then let the Python CLI supply only the official create defaults for omitted form values: seven-day share and purchase lifetimes, `need_buy=false`, category `ui_original`, `Interface/Addons`, empty VIP levels, and version `0`. Submit category IDs as strings even when a discovery response represents them numerically. WA create/update versions contain digits only; update must be numerically greater than the current remote value. Every `!WA:2!` create/update/edit is reparsed by the installed official `WowUIInterface.parseWa` chain, including unchanged edit content. Do not carry create defaults into WA update/edit; omitted existing fields preserve their remote value.

For official NewBeeBox, use only `ncc whoami -o json` to verify authentication; do not inspect its credential files. For third-party Python NewBeeBox, run `newbee session doctor`; credentials must come from the Windows Known Folder auth-store and all authenticated requests must use fixed official HTTPS origins. For DD, run `dd session doctor`; discovery must accept only an Authenticode-valid executable from an allowed official NetEase publisher. Doctor is local-only and must not start a native login. Do not set endpoint, credential-directory, or DD executable-path environment overrides.

For ModUs, require all four `modus session doctor` booleans to be true before an authenticated read or write. A false result means the local Creator session must be repaired in ModUs.Creator; do not ask for or accept token input.

## Own one DD task session

Before any DD live GET or write, run `dd session doctor`. If it reports `gui_running=true`, tell the user that continuing will close the listed official DD GUI instances and ask for explicit consent. Without consent, do not run start, do not close a process, and do not issue a native login. After consent, run `dd session start --confirm-close-gui`; when no GUI is running, run `dd session start` without that flag.

`dd session start` automatically selects the native relogin flow from the official `Account.method`, `Cred.type`, and `Cred.modifier` enums. `urs + urs_token + normal` uses `UrsReLoginFlow` for an email session; `mobile + urs_mobile_token + mobile_password|mobile_uplink` uses `MobileReLoginFlow` for a mobile session. Missing, unknown, or contradictory combinations fail before any flow runs. Never infer the account kind from its text, coerce an enum, or try the other flow after a failure.

Keep the returned opaque `session_id` only in task memory and pass it as `--session <id>` to every DD GET, write, readback, status, and delete. Reuse this one session for the complete task, serialize all commands, stop on the first failure, and never start one session per item in a batch. In a `finally` path, always run `dd session stop --session <id>` and require `cleanup_complete=true`; the ten-minute idle timeout is only an abnormal-exit fallback.

Email and mobile differ only during native relogin. After a matching flow succeeds, both reuse the same JWT refresh, author API client, GET, upload, mutation, readback, logout, and cleanup path through that one task session.

For every DD configuration, first list backups, select `backup_sn`, then run `dd config backup-get --sn <backup>`. Select a WTF account/server/role before presenting that account's known/unknown WA choices. For a retail configuration, present the safe edit-mode and cooldown selector metadata. Send only stable IDs and returned selectors; never request, display, store, or reconstruct raw backup objects or retail import strings.

For a configuration, require a cloud backup already uploaded by the matching desktop client. If none exists, ask the user to upload one in the client and stop before writing.

## Collect every business choice

Expose every business field writable through the selected channel. Do not silently accept a webpage preselection or invent a business default. This includes applicable game type/build, categories, origin, format, visibility, review submission, payment, lifetime, price, room/channel, synchronization, membership, associations, backup content, WTF roles, incremental selections, retail UI data, WA material mode, and install path. When official `ncc` does not expose a webpage field or action, state that capability boundary; do not guess a hidden flag or silently switch to Python.

Use existing remote values only for omitted fields in `edit` or `update`, where omission means preserve. Show candidates by human name plus ID/SN and relevant status. Ask only choices that cannot be determined from the user's explicit request, local artifacts, or remote reads. For CurseForge upload, collect project ID, ZIP path, changelog, release type, version IDs/names or parent file choice, and each requested optional metadata field; do not infer visibility or approval from upload acceptance. For DD, do not draft the executable JSON incrementally: close the full dependency graph first, then generate one final JSON containing parent fields and stable child IDs/selectors. Python repeats the live GETs before upload or mutation and rejects missing or cross-parent selections; detail is authoritative when DD list and detail timestamps differ. When an existing plugin or WA has `assign_user_sn`, only public scope is selectable and the final rebuilt form must remain public.

For ModUs project create/edit, collect the game object; name, alias, summary, category IDs, publish platforms, repository URL, description, dependency IDs, logo/screenshots; and license type, holder, year, and content. Preserve server-managed `logo`, `status`, and `game` detail fields. Project edits use explicit Creator null markers for cleared description, dependencies, and tier. For releases, collect project/file IDs, ZIP, version, release type, changelog, and transaction log path; ZIP parsing derives MD5, sizes, TOC, and supported game versions.

## Prepare and confirm

Create a durable release directory under the target project's root, never under or beside the installed Skill. Use `publish/<YYYYMMDD-HHmmss>-<platform>-<resource>-<action>/`; if that name already exists, append `-2`, `-3`, and so on instead of reusing it. Put every atomic step in a versioned JSON file ordered as `01-<action>.json`, `02-<action>.json`, and so on. A retry or readback for the same plan reuses its directory; a new independent publishing plan gets a new directory. Use JSON, not YAML. Keep the directory after execution as the target project's publishing record, and do not change its ignore rules unless the user asks.

For Python, these are executable `--input` documents using the leaf schema. For official `ncc`, these are redacted plan records containing the channel, working directory, argument vector, non-secret business inputs, local file references, and expected readback; `ncc` does not consume them. Never store a token, API key, raw WA string, raw configuration content, or signed URL in a plan record. Use `@file` or local path references for content. Run `--dry-run` where the selected leaf documents it, especially `ncc wow addons push --dry-run` and every CurseForge upload; do not invent dry-run support for other official commands.

Before the first write, present one complete human-readable plan containing:

- platform, account-visible target name and ID/SN;
- ordered atomic commands;
- every changed, preserved, and explicitly cleared field;
- archive/media/material files and versions;
- backup and all content selections;
- commercial, channel, association, visibility, and review effects;
- possible retained object or uploaded media if a later step fails.

Obtain one explicit confirmation for that exact plan. If the plan changes materially, confirm the changed plan once.

For CurseForge, confirmation must name the public project and numeric ID, ZIP path, selected game-version IDs/names or parent file ID, changelog, release type, optional metadata and relations, and whether manual release is requested. After confirmation, execute exactly one upload attempt. A dry-run performs local validation only and is not remote permission or ID validation.

For a Python delete, first run the resource `get` command, show the exact name and ID/SN, and obtain confirmation for that single record. NewBeeBox delete input contains only the schema, `id`, and `confirm: "DELETE"`; DD delete input contains only the schema, `sn`, and `confirm_delete: true`. Do not reuse confirmation for another record and do not retry an uncertain delete. Official `ncc` currently documents plugin, WA, and configuration main-record deletion as web-only; state that boundary and wait for an explicit third-party selection before offering the Python delete command.

## Execute and verify

Run writes serially. For official `ncc`, always request `-o json`, parse stdout as JSON, and treat stderr only as progress diagnostics. For Python, parse its stable JSON output. Never scrape human text. After each successful step, immediately run the corresponding info/get/list/versions/history command and compare the intended fields in the same DD session when applicable. DD performs a bounded GET-only readback poll and never resends a mutation during verification. For DD plugin update, use a nonempty `/addon/addon_versions` result only as a pre-upload duplicate guard; the matching author-list item's `latest_version` is the primary success confirmation and `detail_v2` is supplementary. Plugin edit also uses the same-SN author projection when detail remains stale. An empty history is diagnostic-only. Treat “submitted for review” and “under review” as distinct from “approved” or “publicly visible.”

When validating a DD authentication change, automated dispatch and constructor tests must cover every supported email and mobile enum combination, select exactly one matching flow with the correct arguments, and reject missing, unknown, or contradictory combinations without fallback. Exercise the shared JWT refresh, author API, resource, broker, sidecar, and logout path once through unified tests; do not require that common path to be repeated per credential kind.

Run the full isolated live matrix only with the official client's currently persisted account and record its safe credential kind; do not switch the persisted account merely to repeat the matrix. For every current non-exploration seasonal build, read the dependency graph and complete plugin and WA create, update, edit, readback, binary upload, delete, and final cleanup. Complete the same configuration matrix, including image upload, only for builds where `/backup/list` and `/backup/detail` provide a usable cloud backup. Record an explicit safe `N/A` reason for every build without one; never silently skip it or fabricate a backup selector. Evidence must record the executed commands, exit status, readback, `N/A` items, implementation commit, DD version, resource hashes, and cleanup result while redacting account names, credential values, tokens, Cookies, JWTs, signed URLs, `clientNo`, raw WA strings, and raw backup content. Cleanup may touch only objects created by that test run, and the run must finish with no sidecar, task broker, or live broker state.

For CurseForge, treat the Upload API's returned file ID as upload acceptance only. Record the ID and command result, then report that moderation, processing, manual release, and public visibility are separate states. On an interrupted or ambiguous upload, do not resend automatically because that can create a duplicate file; inspect the Authors project page or public file list before deciding on a new attempt. Follow the HTTP/error handling table in the CurseForge reference.

In the third-party Python NewBeeBox channel, public plugin publication is three atomic writes: create privately, upload and verify the first version, then edit to public with explicit review intent. Never send a public `share_state` during Python create. In the official channel, follow the installed `ncc docs` sequence for create, init, push, and visibility instead of applying Python wire rules.

For ModUs `plugin create|upload|update`, require the success transaction to record the actual file ID, metadata, signature, and binary-upload stages without the signed URL. A metadata-only `plugin edit` must record no binary upload. Read back with `plugin get`, `list`, and `versions`; for deletion, delete the release before its project and require negative detail readback for each object.

Stop on the first failure. Report completed steps, retained IDs/SNs or media references, the redacted failure stage, whether verification is required, and the smallest safe retry. Explicit DD HTTP/business rejection has `verification_required=false`; interrupted PUT/mutation or failed readback after an accepted write has `verification_required=true`. Native DD failures may include a bounded message, HTTP status, native business code, field validation hints, and `details.log_path`. When `log_path` is present, read only the referenced Fuploader JSONL record under the DD version directory; do not inspect DD's other logs or any credential files. The Fuploader record contains sanitized request and response JSON/body plus byte counts and truncation flags, with signed URLs, cookies, JWTs, credentials, client identifiers, signatures, and tokens recursively redacted. Read back after an uncertain write before resending it. Official NewBeeBox exit codes are `0` success, `1` business error, `2` authentication failure, and `3` network error. Never loop on `quota_exceeded`.

Never print or persist tokens, cookies, JWTs, signed URLs, DD `clientNo`, raw WA strings, or raw configuration backup contents.
