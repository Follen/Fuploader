# Workflow and CLI contract

## Channel selection

DD always uses the bundled Python CLI. NewBeeBox uses official `ncc` by default when installed unless the
user explicitly requests Fupload's third-party Python management tool. If `ncc` is absent, install it when
authorized or necessary for the requested task; otherwise ask. A missing or unsupported official capability does not silently select Python; the user must
explicitly choose the third-party channel, after which remote state and the write plan are rebuilt.

## Command shape

Official NewBeeBox runs the installed `ncc` command described by `ncc docs` and the exact leaf `--help`.
Machine calls include `-o json`. Its exit codes are `0` success, `1` business error, `2` authentication
failure, and `3` network error. Never pass a real credential through `--token`; reuse official local login or
an `NCC_TOKEN` already injected into the Agent environment.

Run `fupload <platform> <resource> <action>` when installed from npm. Only source maintenance or direct-Skill installations without the npm command use `python <skill-root>/scripts/fupload.py <platform> <resource> <action>`. Every command supports `--help`; every write accepts only `--input <path|->`, with optional `--dry-run`.

DD live commands additionally require one opaque `--session <id>`. Run local-only `dd session doctor` first, then `dd session start`. With DD running, this reuses its current browser cookie with ordinary Windows permissions and performs zero native desktop logins; failure never triggers a second login. Without DD running, the stored-credential native flow is used. Reuse the task session for all dependency GETs, serial writes, and readbacks, then always run `dd session stop --session <id>` in `finally`. Borrowed cleanup does not log out the desktop. A task must not start one native login per item.

Output is one JSON object with `schema=fupload.output.v1`, `platform`, `operation`, `success`, and either `data` or `error`. Exit code `0` means success; `2` means validation, session, platform, or verification failure. A DD native/API error may include `details.log_path` pointing to the matching sanitized JSONL record under `<DD version directory>/Fupload/logs/`; read only that record for response JSON/body, HTTP status, native business code, and field hints.

## Python input semantics

- Use the exact `schema` printed by leaf help.
- Unknown fields are errors.
- Required means the action always needs the field.
- Optional means it can be omitted. On edit/update, omission preserves the remote value.
- An explicit `false`, `0`, `[]`, empty string, or `null` is different from omission. Use it only when help/reference permits clearing.
- Local file alternatives do not require the corresponding already-uploaded URL.
- Frontend defaults are not CLI defaults.

## Project publishing records

Use the user's or project's existing release directory and conventions when available; otherwise choose a suitable project or temporary location. Python inputs may also be passed using `--input -`. Retain a redacted record when requested or useful for recovery, and do not put project release files in the installed Skill.

Python inputs use the leaf schema; official `ncc` uses its documented arguments. Do not store tokens, raw WA strings, raw configuration content, cookies, signed URLs, or
other replayable authentication material. Use content file references instead. Only run `--dry-run` when the
official leaf documents it; `ncc wow addons push --dry-run` is the primary supported preflight.

## Mandatory read-modify-write sequence

For Python partial edit/update, the provider performs: target GET, dynamic-option GETs, conversion to a resource-specific form, presence-aware patch, conditional normalization, allowlisted payload build, upload/write, and readback. A failed prerequisite stops the operation.

DD dependency choices are resolved before creating the input file. Changing a parent invalidates descendants. In particular, configuration follows `backup_sn -> backup detail -> WTF account/server/role -> account-scoped known/unknown WA`. Generate one final JSON with parent fields and stable IDs/selectors only. Python repeats the live GETs in the same session before any upload or mutation and rejects stale or cross-parent choices.

For official `ncc`, run the documented info/list/categories/versions/cloudbackup reads needed by the leaf,
apply only flags shown by the installed help, execute once, then read the target back with official commands.
Do not infer hidden flags from the website or translate Python wire fields into undocumented `ncc` options.

## Review and retries

In the Python NewBeeBox channel, plugins are always created privately. If public review was selected, upload and verify the first version before the separate public edit. Other new records follow their platform visibility contract. Updates never change visibility implicitly. If output contains `verification_required`, query the target before any retry.

In official `ncc`, follow the installed docs for create/init/push/edit ordering and review effects. On any
network failure after a write starts, read back before retrying. Do not loop on `quota_exceeded` or treat a
submitted/under-review result as public approval.

Python NewBeeBox delete inputs require one `id` and literal `confirm: "DELETE"`; DD delete inputs require one `sn` and literal `confirm_delete: true`. The provider reads the exact target before deletion and verifies absence from the author list afterward. For multiple authorized targets, handle each individually. Do not retry an uncertain delete or treat deletion of a main record as deletion of its versions or uploaded media. Official `ncc` currently marks plugin, WA, and configuration main-record deletion as web-only; wait for an explicit third-party selection before using Python delete.

## Local artifact checklist

For plugins, inspect TOC interface/build declarations, title/notes/version, addon folders, README, changelog, release archive, logo, and screenshots. For WA, inspect string mode, version, changelog, cover/images, categories, and optional material ZIP/install path. For configurations, select an existing cloud backup or prepare one with the platform's backup scan/generate/upload commands, then select included/ignored content, roles, and incremental-update items.

Cloud-backup deletion uses a separate `backup delete-preview` read and an explicit `backup_ids` write with `confirm_delete:true`. Preview filters do not authorize deleting newly matching records. Every platform checks all owned configuration-share references before deletion and again before each item; referenced backups remain protected and unknown references stop the operation. Record each result and verify absence after deletion. An uncertain result requires readback, never an automatic repeat.
