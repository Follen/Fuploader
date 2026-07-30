# NetEase DD research workspace

This directory contains redacted intermediate artifacts for the NetEase DD
client research. It must not contain raw credentials, cookies, access tokens,
or unredacted user logs.

Research notes:

- `client-inventory.md`: installed client layout and inspected artifacts.
- `auth-analysis.md`: UIBox signing and message JWT authentication.
- `author-api-matrix.md`: plugin/configuration author endpoints and payloads.
- `author-field-coverage.md`: complete author fields, GET dependencies,
  read-modify-write transformations, and validation rules.
- `author-crud-verification.md`: real create/modify/upload results and required GETs.
- `author_schema_probe.py`: read-only response-shape and option probe.
- `author_crud_probe.py`: controlled resource-specific CRUD and upload probe.
- `message-history.md`: channel mapping and time-range retrieval design.
- `headless_probe.py`: read-only runtime probe (`doctor`, `login`, `history`, `author`).
- `stable-sidecar-plan.md`: primary implementation plan and runtime evidence.
- `sidecar-device.json`: stable, non-secret device identity for the research sidecar.
- `remote/`: public production frontend snapshots used for static analysis.
- `client/`: extracted program resources and bytecode used for static analysis.

Final conclusions are maintained in `../dd.md`.

Current default is 方案 A: a Python sidecar with its own stable `clientNo`. The
sidecar can coexist with the DD GUI and does not require in-process injection.

The `history` and `author` commands are diagnostic only. They do not persist
messages or credentials; `author` only creates POST signatures. The older
`author_write_test.py` is an incomplete exploratory builder: its network-write
mode is disabled and it must not be treated as a production implementation.
`author_crud_probe.py` contains the verified resource-specific builders and
still requires an explicit execute phrase for external writes. Never run two
sidecars with the same stable device state concurrently, and never generate a
new client number on every run.
