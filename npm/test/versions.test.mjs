import assert from "node:assert/strict";
import test from "node:test";

import { selectedReleaseTag } from "../lib/versions.mjs";

test("branch refs are not treated as release tags", () => {
  assert.equal(selectedReleaseTag({ env: { GITHUB_REF_NAME: "main" }, argv: [] }), "");
  assert.equal(selectedReleaseTag({ env: { GITHUB_REF_NAME: "feature/v1" }, argv: [] }), "");
});

test("release tags are selected from GitHub or explicit arguments", () => {
  assert.equal(selectedReleaseTag({ env: { GITHUB_REF_NAME: "v0.0.1" }, argv: [] }), "v0.0.1");
  assert.equal(selectedReleaseTag({ env: { GITHUB_REF_NAME: "main" }, argv: ["v0.0.1"] }), "v0.0.1");
});
