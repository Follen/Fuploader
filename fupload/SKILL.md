---
name: fupload
description: Explicit author-publishing workflow for World of Warcraft plugins, configuration shares, and WA/strings on NewBeeBox and NetEase DD. Use only when the user explicitly invokes `$fupload`, explicitly asks to use the Fupload Skill, or loads this Skill by path. Do not trigger from ordinary mentions of publishing, NewBeeBox, DD, plugins, configurations, or WA.
---

# Fupload

Act as the publishing operator. Use the bundled Python CLI only as an atomic read/write tool; keep investigation, choices, planning, confirmation, and recovery in the conversation.

## Locate the CLI

Resolve paths relative to this `SKILL.md`, never relative to the user's project:

```text
python <skill-root>/scripts/fupload.py --help
```

On Windows, prefer `py -3` only if `python` is unavailable. Do not use a binary, Go source, repository-relative fallback, browser automation, Computer Use, or direct handcrafted HTTP calls.

## Establish intent

When the user has not already stated both dimensions, ask in one short message:

1. Platform: NewBeeBox or DD.
2. Resource and action: plugin/configuration/WA, then create/content update/metadata edit.

Map natural language consistently:

- `create`: create the main record. If first content is a separate platform action, plan it as a following atomic step.
- `update`: publish a plugin version, change selected configuration-backup content, or publish a WA/string version.
- `edit`: change metadata, media, categories, commercial settings, associations, channels, or explicit public/review state.

Never offer delete, drafts, guides, messages, or GUI automation.

## Load only the needed contract

- Read [references/workflow.md](references/workflow.md) for every write workflow.
- Read [references/newbee.md](references/newbee.md) only for NewBeeBox.
- Read [references/dd.md](references/dd.md) only for DD.
- Run the exact leaf command with `--help` before creating its input. Treat help as the executable schema contract.

## Investigate

Inspect the user-provided project or current workspace for `.toc`, README, changelog, Git changes, archives, screenshots, logos, and WA material files. Do not modify or package the user's project until that is part of the agreed plan.

Use read-only CLI commands to discover the current account's records, target detail, versions, backups, categories, game branches/builds, installation paths, life types, VIP levels, channels, and association candidates. Never ask the user to copy an ID that the CLI can query.

Run the platform session doctor before authenticated reads. NewBee credentials must come from the Windows Known Folder auth-store and all authenticated requests must use the CLI's fixed official HTTPS origins. DD discovery must accept only an Authenticode-valid executable from an allowed official NetEase publisher. Do not set endpoint, credential-directory, or DD executable-path environment overrides.

For a DD retail configuration, read `dd config backup-get` and present the safe edit-mode and cooldown selector metadata. Send only returned selectors in `retail_ui_config`; never request, display, or reconstruct raw retail import strings.

For a configuration, require a cloud backup already uploaded by the matching desktop client. If none exists, ask the user to upload one in the client and stop before writing.

## Collect every business choice

Expose every selectable page field to the user. Do not silently accept a webpage preselection or invent a business default. This includes game type/build, categories, origin, format, visibility, review submission, payment, lifetime, price, room/channel, synchronization, membership, associations, backup content, WTF roles, incremental selections, retail UI data, WA material mode, and install path.

Use existing remote values only for omitted fields in `edit` or `update`, where omission means preserve. Show candidates by human name plus ID/SN and relevant status. Ask only choices that cannot be determined from the user's explicit request, local artifacts, or remote reads.

## Prepare and confirm

Create a durable release directory under the target project's root, never under or beside the installed Skill. Use `publish/<YYYYMMDD-HHmmss>-<platform>-<resource>-<action>/`; if that name already exists, append `-2`, `-3`, and so on instead of reusing it. Put every versioned JSON input for one publishing plan in that directory, ordered as `01-<action>.json`, `02-<action>.json`, and so on. A retry or readback for the same plan reuses its directory; a new independent publishing plan gets a new directory. Use JSON, not YAML. Keep the directory after execution as the project's publishing record, and do not change the target project's ignore rules unless the user asks. Run each intended command with `--dry-run`; remember that dry-run validates only schema and local files.

Before the first write, present one complete human-readable plan containing:

- platform, account-visible target name and ID/SN;
- ordered atomic commands;
- every changed, preserved, and explicitly cleared field;
- archive/media/material files and versions;
- backup and all content selections;
- commercial, channel, association, visibility, and review effects;
- possible retained object or uploaded media if a later step fails.

Obtain one explicit confirmation for that exact plan. If the plan changes materially, confirm the changed plan once.

## Execute and verify

Run writes serially. Parse JSON output; never scrape human text. After each successful step, immediately run the corresponding get/list/version/history command and compare the intended fields. Treat “submitted for review” and “under review” as distinct from “approved” or “publicly visible.”

Stop on the first failure. Report completed steps, retained IDs/SNs or media references, the redacted failure, whether verification is required, and the smallest safe retry. When a write result is uncertain, read back first and do not automatically resend.

Never print or persist tokens, cookies, JWTs, signed URLs, DD `clientNo`, raw WA strings, or raw configuration backup contents.
