import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { managedInstallFile, readManagedInstall, recordManagedSkill } from "../lib/managed-install.mjs";
import { CURSEFORGE_ENV_TEMPLATE, curseForgeEnvPath, ensureCurseForgeEnv } from "../lib/curseforge-config.mjs";
import { ensureSkill } from "../lib/skill-installer.mjs";
import { cleanupManagedSkills, resolveGlobalInstall, resolveNpmCli, uninstallSelf } from "../lib/uninstall.mjs";
import { updateSelf } from "../lib/update.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const packageVersion = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8")).version;

function temporaryDirectory(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "fupload-uninstall-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function managedOptions(root) {
  return {
    platform: "linux",
    env: { XDG_STATE_HOME: path.join(root, "state") },
    home: path.join(root, "home"),
  };
}

test("records all managed Skill targets without duplicates", (t) => {
  const root = temporaryDirectory(t);
  const options = managedOptions(root);
  recordManagedSkill(path.join(root, "one"), options);
  recordManagedSkill(path.join(root, "two"), options);
  recordManagedSkill(path.join(root, "one"), options);
  assert.equal(readManagedInstall(options).targets.length, 2);
  assert.ok(fs.existsSync(managedInstallFile(options)));
});

test("cleanup removes every stamped Skill and preserves unknown directories", async (t) => {
  const root = temporaryDirectory(t);
  const options = managedOptions(root);
  const first = path.join(root, "skills", "one");
  const second = path.join(root, "skills", "two");
  const unknown = path.join(root, "skills", "unknown");
  for (const target of [first, second]) {
    await ensureSkill({ packageRoot, target });
    recordManagedSkill(target, options);
  }
  fs.mkdirSync(unknown, { recursive: true });
  fs.writeFileSync(path.join(unknown, "user.txt"), "keep", "utf8");
  recordManagedSkill(unknown, options);
  const result = await cleanupManagedSkills({ ...options, extraTargets: [] });
  assert.equal(fs.existsSync(first), false);
  assert.equal(fs.existsSync(second), false);
  assert.equal(fs.readFileSync(path.join(unknown, "user.txt"), "utf8"), "keep");
  assert.equal(result.skills.find((entry) => entry.target === path.resolve(unknown)).status, "preserved_unmanaged");
});

test("cleanup failure leaves the registry for a retry", async (t) => {
  const root = temporaryDirectory(t);
  const options = managedOptions(root);
  const target = path.join(root, "skill");
  await ensureSkill({ packageRoot, target });
  recordManagedSkill(target, options);
  await assert.rejects(
    cleanupManagedSkills({
      ...options,
      removePath() {
        throw new Error("locked");
      },
    }),
    /could not be removed/,
  );
  assert.ok(fs.existsSync(target));
  assert.ok(fs.existsSync(managedInstallFile(options)));
});

test("global installation prefix is resolved from the package location", (t) => {
  const root = temporaryDirectory(t);
  const prefix = path.join(root, "prefix");
  const fakePackage = process.platform === "win32"
    ? path.join(prefix, "node_modules", "@follenfang", "fupload")
    : path.join(prefix, "lib", "node_modules", "@follenfang", "fupload");
  const launcher = process.platform === "win32"
    ? path.join(prefix, "fupload.cmd")
    : path.join(prefix, "bin", "fupload");
  fs.mkdirSync(fakePackage, { recursive: true });
  fs.mkdirSync(path.dirname(launcher), { recursive: true });
  fs.writeFileSync(launcher, "launcher", "utf8");
  assert.equal(resolveGlobalInstall(fakePackage).prefix, path.resolve(prefix));
});

test("an injected npm exec path is used without shell lookup", (t) => {
  const root = temporaryDirectory(t);
  const npmCli = path.join(root, "npm-cli.js");
  fs.writeFileSync(npmCli, "", "utf8");
  assert.equal(resolveNpmCli({ env: { npm_execpath: npmCli } }), path.resolve(npmCli));
});

test("self uninstall cleans the Skill before asking npm to remove the package", async (t) => {
  const root = temporaryDirectory(t);
  const options = managedOptions(root);
  const prefix = path.join(root, "prefix");
  const fakePackage = path.join(prefix, "lib", "node_modules", "@follenfang", "fupload");
  const launcher = path.join(prefix, "bin", "fupload");
  fs.mkdirSync(fakePackage, { recursive: true });
  fs.mkdirSync(path.dirname(launcher), { recursive: true });
  fs.writeFileSync(launcher, "launcher", "utf8");
  const target = path.join(root, "skill");
  await ensureSkill({ packageRoot, target });
  recordManagedSkill(target, options);
  const curseforgeConfig = ensureCurseForgeEnv(options).path;
  fs.writeFileSync(curseforgeConfig, "CURSEFORGE_UPLOAD_TOKEN=keep\n", "utf8");
  let npmArgs;
  const result = await uninstallSelf({
    packageRoot: fakePackage,
    target,
    ...options,
    runNpm(args) {
      npmArgs = args;
      assert.equal(fs.existsSync(target), false);
      fs.rmSync(launcher, { force: true });
      fs.rmSync(fakePackage, { recursive: true, force: true });
      return { status: 0, stdout: "", stderr: "" };
    },
  });
  assert.equal(result.success, true);
  assert.equal(fs.readFileSync(curseForgeEnvPath(options), "utf8"), "CURSEFORGE_UPLOAD_TOKEN=keep\n");
  assert.deepEqual(npmArgs, ["uninstall", "-g", "--ignore-scripts", "--prefix", path.resolve(prefix), "@follenfang/fupload"]);
});

test("self update installs latest and synchronizes managed Skills", async (t) => {
  const root = temporaryDirectory(t);
  const options = managedOptions(root);
  const prefix = path.join(root, "prefix");
  const fakePackage = path.join(prefix, "lib", "node_modules", "@follenfang", "fupload");
  const launcher = path.join(prefix, "bin", "fupload");
  const manifest = JSON.parse(fs.readFileSync(path.join(packageRoot, "npm", "skill-manifest.json"), "utf8"));
  fs.mkdirSync(path.join(fakePackage, "npm"), { recursive: true });
  fs.mkdirSync(path.dirname(launcher), { recursive: true });
  fs.copyFileSync(path.join(packageRoot, "package.json"), path.join(fakePackage, "package.json"));
  fs.copyFileSync(path.join(packageRoot, "npm", "skill-manifest.json"), path.join(fakePackage, "npm", "skill-manifest.json"));
  for (const entry of manifest.files) {
    const source = path.join(packageRoot, "fupload", ...entry.path.split("/"));
    const destination = path.join(fakePackage, "fupload", ...entry.path.split("/"));
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(source, destination);
  }
  fs.writeFileSync(launcher, "launcher", "utf8");
  const target = path.join(root, "custom-skill");
  let npmArgs;
  const result = await updateSelf({
    packageRoot: fakePackage,
    target,
    ...options,
    runNpm(args) {
      npmArgs = args;
      return { status: 0, stdout: "", stderr: "" };
    },
  });
  assert.equal(result.success, true);
  assert.equal(result.from_version, packageVersion);
  assert.equal(result.to_version, packageVersion);
  assert.deepEqual(npmArgs, ["install", "-g", "--ignore-scripts", "--prefix", path.resolve(prefix), "@follenfang/fupload@latest"]);
  assert.ok(fs.existsSync(path.join(target, ".fupload-npm-install.json")));
  assert.equal(result.curseforge_config.path, curseForgeEnvPath(options));
  assert.equal(fs.readFileSync(result.curseforge_config.path, "utf8"), CURSEFORGE_ENV_TEMPLATE);
});
