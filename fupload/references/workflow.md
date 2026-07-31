# Workflow and CLI contract

## Command shape

Run `python <skill-root>/scripts/fupload.py <platform> <resource> <action>`. Every command supports `--help`; every write accepts only `--input <path|->`, with optional `--dry-run`.

Output is one JSON object with `schema=fupload.output.v1`, `platform`, `operation`, `success`, and either `data` or `error`. Exit code `0` means success; `2` means validation, session, platform, or verification failure.

## Input semantics

- Use the exact `schema` printed by leaf help.
- Unknown fields are errors.
- Required means the action always needs the field.
- Optional means it can be omitted. On edit/update, omission preserves the remote value.
- An explicit `false`, `0`, `[]`, empty string, or `null` is different from omission. Use it only when help/reference permits clearing.
- Local file alternatives do not require the corresponding already-uploaded URL.
- Frontend defaults are not CLI defaults.

## Mandatory read-modify-write sequence

For partial edit/update, the provider performs: target GET, dynamic-option GETs, conversion to a resource-specific form, presence-aware patch, conditional normalization, allowlisted payload build, upload/write, and readback. A failed prerequisite stops the operation.

## Review and retries

New records remain private unless the input explicitly selects public and review submission. Updates never change visibility implicitly. If output contains `verification_required`, query the target before any retry.

## Local artifact checklist

For plugins, inspect TOC interface/build declarations, title/notes/version, addon folders, README, changelog, release archive, logo, and screenshots. For WA, inspect string mode, version, changelog, cover/images, categories, and optional material ZIP/install path. For configurations, select an existing cloud backup, all included/ignored content, roles, and incremental-update items.
