import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { INSTALL_STAMP, ensureSkill, loadDistribution, verifySkill } from "../lib/skill-installer.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function temporaryDirectory(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "fupload-installer-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test("installs, validates, and reuses the current Skill", async (t) => {
  const target = path.join(temporaryDirectory(t), "skill");
  const installed = await ensureSkill({ packageRoot, target });
  assert.equal(installed.status, "installed");
  assert.ok(fs.existsSync(path.join(target, INSTALL_STAMP)));
  assert.equal(verifySkill(target, installed.distribution.manifest).valid, true);
  assert.equal((await ensureSkill({ packageRoot, target })).status, "current");
});

test("text validation is stable across LF and CRLF", async (t) => {
  const target = path.join(temporaryDirectory(t), "skill");
  const installed = await ensureSkill({ packageRoot, target });
  const skillFile = path.join(target, "SKILL.md");
  fs.writeFileSync(skillFile, fs.readFileSync(skillFile, "utf8").replace(/\r?\n/g, "\r\n"), "utf8");
  assert.equal(verifySkill(target, installed.distribution.manifest).valid, true);
});

test("repairs a changed managed Skill through a transactional upgrade", async (t) => {
  const target = path.join(temporaryDirectory(t), "skill");
  const installed = await ensureSkill({ packageRoot, target });
  fs.appendFileSync(path.join(target, "SKILL.md"), "changed\n", "utf8");
  const upgraded = await ensureSkill({ packageRoot, target });
  assert.equal(upgraded.status, "upgraded");
  assert.equal(verifySkill(target, installed.distribution.manifest).valid, true);
});

test("fails closed for an unrelated existing target", async (t) => {
  const target = path.join(temporaryDirectory(t), "skill");
  fs.mkdirSync(target, { recursive: true });
  fs.writeFileSync(path.join(target, "SKILL.md"), "unrelated\n", "utf8");
  await assert.rejects(ensureSkill({ packageRoot, target }), /not a matching managed Fuploader Skill/);
});

test("distribution manifest matches package metadata", () => {
  const distribution = loadDistribution(packageRoot);
  assert.equal(distribution.packageRecord.name, "@follenfang/fupload");
  assert.equal(distribution.packageRecord.version, distribution.manifest.skill_version);
});
