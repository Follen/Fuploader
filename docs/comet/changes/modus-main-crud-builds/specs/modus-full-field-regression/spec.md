# ModUs Full-Field Integration

## Authentication and clients
Fupload SHALL reuse the separate local authenticated sessions of ModUs.Creator and the ModUs main client. It SHALL expose diagnostic readiness without returning credentials. Creator project/plugin requests SHALL use the Creator session; configuration, WA/string and main-media requests SHALL use the main-client session.

## Creator project and image protocol
Fupload SHALL model every Creator project field exposed by the installed client, including state-machine ordering, dropdown enums, at-least-one platform selection, the real no-tier branch, all license subfields, dependencies, repository, logo/screenshot creation payload and edit image operations. A real regression SHALL mutate every writable field independently, read it back, restore it and read the restoration back. Local project images SHALL be submitted through the exact official create or edit image wire form and their server-managed result SHALL be read back.

## Creator plugin release protocol
Fupload SHALL support project and release discovery plus real release create, upload, update, metadata edit and delete. It SHALL derive and submit the exact ZIP metadata, allocate a file ID, obtain a signed upload URL, PUT the original ZIP bytes, read back all release fields and clean up in dependency order. Evidence SHALL bind the ZIP input to the uploaded object with length and SHA-256 while removing signed URL material.

## Main-client Build protocol
Fupload SHALL expose all confirmed Build IDs and use the selected Build consistently in request body `server` and `X-Server-Type`. Backup, configuration and WA/string list operations SHALL run successfully for each Build with exact official defaults and filters. Business error responses SHALL remain errors.

## Configuration fields and media
Fupload SHALL model all official configuration list and write fields, their types, defaults, enums and interdependencies. It SHALL upload a local cover/image using the official main-client binary image protocol, extract the reusable server reference, use it in real create and update requests, and verify the detail response. Every other writable configuration field SHALL undergo the same mutate/read/restore/read cycle. Delete success SHALL follow the service's soft-delete semantics and active-list exclusion.

## WA/string fields, versions and media
Fupload SHALL model all official WA/string list, article, code, version, applicable-addon, tag, publication, payment, synchronization, platform, tier and Build fields. It SHALL upload a local cover/image using the official main-client binary image protocol, use the returned reference in real create and update requests and verify the detail response. It SHALL also publish, read and delete a real version and finally soft-delete the test article.

## Field matrix and validation
Documentation SHALL contain complete Creator project/release, configuration and WA/string field matrices with CLI name, wire name, JSON type, required/default behavior, enum source, state dependency, write endpoint and readback location. Positive and negative regression SHALL cover dropdown values, empty/null branches, mutually constrained fields, at-least-one selections, current no-tier behavior and all Builds. Invalid combinations SHALL fail before remote mutation.

## Evidence and release
Real regression evidence SHALL be generated against the final implementation and record each command, redacted input summary, response summary and exit status. Mutable content, image and ZIP inputs SHALL include length and SHA-256 rather than raw bytes/text. The final release SHALL be newer than 0.0.12, pushed to GitHub, pass Windows and Ubuntu CI plus Trusted Publishing, match the npm registry/latest version and install globally.
