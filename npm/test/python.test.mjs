import assert from "node:assert/strict";
import test from "node:test";

import { discoverPython } from "../lib/python.mjs";

test("discovers a supported local Python interpreter", () => {
  const python = discoverPython();
  assert.ok(python);
  assert.equal(python.version[0], 3);
  assert.ok(python.version[1] >= 9);
});
