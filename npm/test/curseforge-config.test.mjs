import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CURSEFORGE_ENV_TEMPLATE,
  curseForgeEnvPath,
  ensureCurseForgeEnv,
} from "../lib/curseforge-config.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function temporaryDirectory(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "fupload-curseforge-config-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test("creates the fixed CurseForge environment template with private POSIX permissions", (t) => {
  const home = temporaryDirectory(t);
  const result = ensureCurseForgeEnv({ home, platform: "linux" });
  assert.equal(result.status, "created");
  assert.equal(result.path, curseForgeEnvPath({ home }));
  assert.equal(fs.readFileSync(result.path, "utf8"), CURSEFORGE_ENV_TEMPLATE);
  if (process.platform !== "win32") {
    assert.equal(fs.statSync(result.path).mode & 0o777, 0o600);
  }
});

test("preserves an existing CurseForge environment file byte for byte", (t) => {
  const home = temporaryDirectory(t);
  const filename = curseForgeEnvPath({ home });
  const existing = Buffer.from("CURSEFORGE_AUTHOR_ID=42\r\nCUSTOM=value\r\n", "utf8");
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  fs.writeFileSync(filename, existing, { mode: 0o644 });
  const beforeMode = fs.statSync(filename).mode;
  const result = ensureCurseForgeEnv({ home, platform: "linux" });
  assert.equal(result.status, "preserved");
  assert.deepEqual(fs.readFileSync(filename), existing);
  assert.equal(fs.statSync(filename).mode, beforeMode);
});

test("postinstall and first launcher use initialize the same home configuration", (t) => {
  const root = temporaryDirectory(t);
  const home = path.join(root, "home");
  const skill = path.join(root, "skill");
  const env = {
    ...process.env,
    HOME: home,
    USERPROFILE: home,
    FUPLOAD_AGENT_HOME: path.join(root, "agent"),
  };
  const postinstall = spawnSync(process.execPath, [path.join(packageRoot, "npm", "postinstall.mjs")], {
    cwd: packageRoot,
    env,
    encoding: "utf8",
  });
  assert.equal(postinstall.status, 0, postinstall.stderr);
  const filename = curseForgeEnvPath({ home });
  assert.equal(fs.readFileSync(filename, "utf8"), CURSEFORGE_ENV_TEMPLATE);

  const custom = "CURSEFORGE_AUTHOR_ID=138844367\nCURSEFORGE_API_KEY=keep\nCURSEFORGE_UPLOAD_TOKEN=keep\n";
  fs.writeFileSync(filename, custom, "utf8");
  const launcher = spawnSync(
    process.execPath,
    [path.join(packageRoot, "npm", "bin", "fupload.mjs"), "--skill-dir", skill, "--version"],
    { cwd: packageRoot, env, encoding: "utf8" },
  );
  assert.equal(launcher.status, 0, launcher.stderr);
  assert.equal(fs.readFileSync(filename, "utf8"), custom);
});
