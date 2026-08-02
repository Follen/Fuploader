import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { parseLauncherOptions, resolveSkillDirectory } from "../lib/options.mjs";

test("launcher options are removed before Python forwarding", () => {
  const result = parseLauncherOptions([
    "dd", "session", "doctor", "--skill-dir", "custom-skill",
  ]);
  assert.equal(result.skillDirectory, "custom-skill");
  assert.deepEqual(result.forwarded, ["dd", "session", "doctor"]);
});

test("explicit Skill directory wins over the Agent home", () => {
  assert.equal(
    resolveSkillDirectory({ explicit: "explicit", env: { FUPLOAD_AGENT_HOME: "agent" }, home: "home" }),
    path.resolve("explicit"),
  );
});

test("Agent home resolves to skills/fupload", () => {
  assert.equal(
    resolveSkillDirectory({ env: { FUPLOAD_AGENT_HOME: path.join("root", "agent") }, home: "home" }),
    path.resolve("root", "agent", "skills", "fupload"),
  );
});

test("missing --skill-dir value is rejected", () => {
  assert.throws(() => parseLauncherOptions(["--skill-dir"]), /requires a directory/);
});
